from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import (
    ActionTemplate,
    CivicChallenge,
    Notification,
    OrganizationAccount,
    Project,
    ProjectOutcome,
    User,
)
from app.routes import admin_required, create_notification
from app.services.email_service import send_outcome_approved
from app.services.template_generator import can_generate_template, convert_to_template
from app.utils import strip_html, utcnow


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _paginate(query, per_page=20):
    page = max(1, request.args.get("page", 1, type=int))
    return query.paginate(page=page, per_page=per_page, error_out=False)


@admin_bp.get("")
@login_required
@admin_required
def dashboard():
    stats = {
        "total_users": User.query.count(),
        "active_projects": Project.query.filter(Project.status.in_(["assembling", "active", "launch_ready"])).count(),
        "completed_projects": Project.query.filter_by(status="completed").count(),
        "pending_outcomes": ProjectOutcome.query.filter_by(is_published=False).count(),
        "flagged_projects": Project.query.filter_by(is_flagged=True).count(),
        "total_templates": ActionTemplate.query.count(),
        "organizations": OrganizationAccount.query.count(),
    }
    recent_activity = Notification.query.order_by(Notification.created_at.desc()).limit(10).all()
    return render_template("admin/dashboard.html", stats=stats, recent_activity=recent_activity)


@admin_bp.get("/projects")
@login_required
@admin_required
def projects():
    reason_filter = request.args.get("reason", "").strip()
    query = Project.query.filter_by(is_flagged=True)
    if reason_filter:
        query = query.filter(Project.flag_reason.ilike(f"%{reason_filter}%"))

    pagination = _paginate(query.order_by(Project.updated_at.desc()))
    return render_template("admin/projects.html", pagination=pagination, reason_filter=reason_filter)


@admin_bp.post("/projects/<int:id>/unflag")
@login_required
@admin_required
def unflag_project(id):
    project = Project.query.get_or_404(id)
    project.is_flagged = False
    project.flag_reason = None
    db.session.commit()
    flash("Project unflagged.", "success")
    return redirect(url_for("admin.projects"))


@admin_bp.post("/projects/<int:id>/archive")
@login_required
@admin_required
def archive_project(id):
    project = Project.query.get_or_404(id)
    project.status = "archived"
    db.session.commit()
    flash("Project archived.", "success")
    return redirect(url_for("admin.projects"))


@admin_bp.post("/projects/<int:id>/warn")
@login_required
@admin_required
def warn_project_creator(id):
    project = Project.query.get_or_404(id)
    message = strip_html(request.form.get("message", "Please review your project content."), 1000)

    create_notification(
        project.creator_user_id,
        "moderation_warning",
        f"Moderation warning: {project.title}",
        message,
        f"/my-projects/{project.id}/manage",
    )
    db.session.commit()

    flash("Warning email sent.", "success")
    return redirect(url_for("admin.projects"))


@admin_bp.get("/outcomes")
@login_required
@admin_required
def outcomes():
    query = ProjectOutcome.query.filter_by(is_published=False).order_by(ProjectOutcome.submitted_at.desc())
    pagination = _paginate(query)
    return render_template("admin/outcomes.html", pagination=pagination)


@admin_bp.get("/outcomes/<int:id>")
@login_required
@admin_required
def outcome_detail(id):
    outcome = ProjectOutcome.query.get_or_404(id)
    return render_template("admin/outcome_detail.html", outcome=outcome)


@admin_bp.post("/outcomes/<int:id>/approve")
@login_required
@admin_required
def approve_outcome(id):
    outcome = ProjectOutcome.query.get_or_404(id)
    rating = strip_html(request.form.get("outcome_rating", "partial_success"), 50)
    if rating not in {"full_success", "partial_success", "not_achieved"}:
        rating = "partial_success"

    outcome.is_published = True
    outcome.outcome_rating = rating
    db.session.commit()

    project = outcome.project

    if can_generate_template(project.id):
        has_template = ActionTemplate.query.filter_by(source_project_id=project.id).first()
        if not has_template:
            convert_to_template(project.id)

    create_notification(
        project.creator_user_id,
        "outcome_approved",
        f"Outcome approved for {project.title}",
        "Your outcome report is now published.",
        f"/projects/{project.id}",
    )
    db.session.commit()

    try:
        send_outcome_approved(project.creator, project)
    except Exception:
        pass

    flash("Outcome approved and published.", "success")
    return redirect(url_for("admin.outcomes"))


@admin_bp.post("/outcomes/<int:id>/reject")
@login_required
@admin_required
def reject_outcome(id):
    outcome = ProjectOutcome.query.get_or_404(id)
    reason = strip_html(request.form.get("reason", "Please revise and resubmit."), 1000)

    create_notification(
        outcome.project.creator_user_id,
        "outcome_rejected",
        f"Outcome report needs revision: {outcome.project.title}",
        reason,
        f"/my-projects/{outcome.project.id}/outcome",
    )

    db.session.delete(outcome)
    db.session.commit()
    flash("Outcome rejected. Creator notified.", "info")
    return redirect(url_for("admin.outcomes"))


@admin_bp.get("/blog")
@login_required
@admin_required
def blog():
    from app.routes.main import BLOG_POSTS

    return render_template("admin/blog.html", posts=BLOG_POSTS)


@admin_bp.get("/templates")
@login_required
@admin_required
def templates():
    q = request.args.get("q", "").strip()
    query = ActionTemplate.query
    if q:
        query = query.filter(ActionTemplate.title.ilike(f"%{q}%"))

    pagination = _paginate(query.order_by(ActionTemplate.updated_at.desc()))
    return render_template("admin/templates.html", pagination=pagination, q=q)


@admin_bp.post("/templates/<int:id>/upgrade")
@login_required
@admin_required
def template_upgrade(id):
    template = ActionTemplate.query.get_or_404(id)
    tier = strip_html(request.form.get("quality_tier", "silver"), 20).lower()
    if tier not in {"bronze", "silver", "gold"}:
        tier = "silver"
    template.quality_tier = tier
    db.session.commit()
    flash(f"Template upgraded to {tier.title()}.", "success")
    return redirect(url_for("admin.templates"))


@admin_bp.post("/templates/<int:id>/unpublish")
@login_required
@admin_required
def template_unpublish(id):
    template = ActionTemplate.query.get_or_404(id)
    template.is_published = False
    db.session.commit()
    flash("Template unpublished.", "info")
    return redirect(url_for("admin.templates"))


@admin_bp.post("/templates/<int:id>/tier")
@login_required
@admin_required
def template_tier(id):
    return template_upgrade(id)


@admin_bp.get("/challenges")
@login_required
@admin_required
def challenges():
    pagination = _paginate(CivicChallenge.query.order_by(CivicChallenge.created_at.desc()))
    return render_template("admin/challenges.html", pagination=pagination)


@admin_bp.get("/users")
@login_required
@admin_required
def users():
    account_type = request.args.get("account_type", "").strip()
    subscription_tier = request.args.get("subscription_tier", "").strip()
    is_verified = request.args.get("is_verified", "").strip().lower()
    is_admin_filter = request.args.get("is_admin", "").strip().lower()
    q = request.args.get("q", "").strip()

    query = User.query
    if account_type:
        query = query.filter_by(account_type=account_type)
    if subscription_tier:
        query = query.filter_by(subscription_tier=subscription_tier)
    if is_verified in {"true", "false"}:
        query = query.filter_by(is_verified=(is_verified == "true"))
    if is_admin_filter in {"true", "false"}:
        query = query.filter_by(is_admin=(is_admin_filter == "true"))
    if q:
        query = query.filter(
            or_(
                User.email.ilike(f"%{q}%"),
                User.first_name.ilike(f"%{q}%"),
                User.last_name.ilike(f"%{q}%"),
                User.username.ilike(f"%{q}%"),
            )
        )

    pagination = _paginate(query.order_by(User.created_at.desc()))
    return render_template("admin/users.html", pagination=pagination)


@admin_bp.post("/users/<int:id>/disable")
@login_required
@admin_required
def disable_user(id):
    user = User.query.get_or_404(id)
    user.is_disabled = True
    db.session.commit()
    flash("User account disabled.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/enable")
@login_required
@admin_required
def enable_user(id):
    user = User.query.get_or_404(id)
    user.is_disabled = False
    db.session.commit()
    flash("User account re-enabled.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/grant-admin")
@login_required
@admin_required
def grant_admin(id):
    user = User.query.get_or_404(id)
    user.is_admin = True
    db.session.commit()
    flash("Admin access granted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/revoke-admin")
@login_required
@admin_required
def revoke_admin(id):
    user = User.query.get_or_404(id)
    user.is_admin = False
    db.session.commit()
    flash("Admin access revoked.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/toggle-admin")
@login_required
@admin_required
def toggle_admin(id):
    user = User.query.get_or_404(id)
    if user.is_admin:
        user.is_admin = False
        message = "Admin access revoked."
        category = "info"
    else:
        user.is_admin = True
        message = "Admin access granted."
        category = "success"
    db.session.commit()
    flash(message, category)
    return redirect(url_for("admin.users"))


@admin_bp.get("/organizations")
@login_required
@admin_required
def organizations():
    pagination = _paginate(OrganizationAccount.query.order_by(OrganizationAccount.org_name.asc()))
    return render_template("admin/organizations.html", pagination=pagination)


@admin_bp.post("/organizations/<int:id>/verify")
@login_required
@admin_required
def verify_organization(id):
    org = OrganizationAccount.query.get_or_404(id)
    org.is_verified = True
    db.session.commit()
    flash("Organization verified.", "success")
    return redirect(url_for("admin.organizations"))


@admin_bp.post("/organizations/<int:id>/revoke")
@login_required
@admin_required
def revoke_organization_verification(id):
    org = OrganizationAccount.query.get_or_404(id)
    org.is_verified = False
    db.session.commit()
    flash("Organization verification revoked.", "info")
    return redirect(url_for("admin.organizations"))


@admin_bp.get("/analytics")
@login_required
@admin_required
def analytics():
    range_key = request.args.get("range", "30d")
    day_map = {"7d": 7, "30d": 30, "90d": 90}
    days = day_map.get(range_key, 30)
    since = utcnow() - timedelta(days=days)

    metrics = {
        "new_users": User.query.filter(User.created_at >= since).count(),
        "new_projects": Project.query.filter(Project.created_at >= since).count(),
        "completed_projects": Project.query.filter(Project.updated_at >= since, Project.status == "completed").count(),
        "new_templates": ActionTemplate.query.filter(ActionTemplate.updated_at >= since).count(),
    }

    return render_template("admin/analytics.html", metrics=metrics, range_key=range_key)


@admin_bp.get("/email-logs")
@login_required
@admin_required
def email_logs():
    type_filter = request.args.get("email_type", "").strip()
    status_filter = request.args.get("status", "").strip()

    query = Notification.query
    if type_filter:
        query = query.filter(Notification.notification_type.ilike(f"%{type_filter}%"))

    pagination = _paginate(query.order_by(Notification.created_at.desc()))
    return render_template(
        "admin/email_logs.html",
        pagination=pagination,
        type_filter=type_filter,
        status_filter=status_filter,
    )


@admin_bp.post("/email-logs/<int:id>/resend")
@login_required
@admin_required
def resend_email_log(id):
    Notification.query.get_or_404(id)
    flash("Email resend queued.", "success")
    return redirect(url_for("admin.email_logs"))
