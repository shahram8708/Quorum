from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Project, ProjectRole, RoleApplication, Task
from app.routes import create_notification
from app.services.email_service import (
    send_application_accepted,
    send_application_declined,
    send_launch_notification,
)
from app.services.mvt_notifier import check_mvt
from app.utils import strip_html, utcnow


manage_bp = Blueprint("manage", __name__, url_prefix="/my-projects")


def _owner_or_403(project):
    if project.creator_user_id != current_user.id:
        from flask import abort

        abort(403)


def _project_nav_counts(project_id):
    pending_applications_count = RoleApplication.query.filter_by(project_id=project_id, status="pending").count()
    overdue_tasks_count = (
        Task.query.filter_by(project_id=project_id)
        .filter(Task.status != "done", Task.due_date.isnot(None), Task.due_date < date.today())
        .count()
    )
    return pending_applications_count, overdue_tasks_count


@manage_bp.get("")
@login_required
def my_projects():
    status_filter = request.args.get("status", "").strip()
    query = Project.query.filter_by(creator_user_id=current_user.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    projects = query.order_by(Project.created_at.desc()).all()
    return render_template(
        "manage/dashboard.html",
        projects=projects,
        project=None,
        status_filter=status_filter,
    )


@manage_bp.get("/<int:id>/manage")
@login_required
def manage_dashboard(id):
    project = Project.query.get_or_404(id)
    _owner_or_403(project)

    pending_count, overdue_tasks_count = _project_nav_counts(id)
    recent_activity = project.feed_posts[:10]

    return render_template(
        "manage/dashboard.html",
        project=project,
        projects=None,
        active_tab="overview",
        pending_applications_count=pending_count,
        overdue_tasks_count=overdue_tasks_count,
        pending_count=pending_count,
        recent_activity=recent_activity,
    )


@manage_bp.get("/<int:id>/team")
@login_required
def manage_team(id):
    project = Project.query.get_or_404(id)
    _owner_or_403(project)

    applications = (
        RoleApplication.query.filter_by(project_id=id)
        .order_by(RoleApplication.applied_at.desc())
        .all()
    )
    accepted_members = [role for role in project.roles if role.is_filled and role.filled_by_user]
    pending_count, overdue_tasks_count = _project_nav_counts(id)

    return render_template(
        "manage/team.html",
        project=project,
        applications=applications,
        accepted_members=accepted_members,
        active_tab="team",
        pending_applications_count=pending_count,
        overdue_tasks_count=overdue_tasks_count,
    )


@manage_bp.post("/<int:id>/team/accept/<int:app_id>")
@login_required
def accept_application(id, app_id):
    project = Project.query.get_or_404(id)
    _owner_or_403(project)

    application = RoleApplication.query.filter_by(id=app_id, project_id=id).first_or_404()
    role = ProjectRole.query.filter_by(id=application.role_id, project_id=id).first_or_404()

    if role.is_filled:
        flash("Role already filled.", "warning")
        return redirect(url_for("manage.manage_team", id=id))

    role.is_filled = True
    role.filled_by_user_id = application.applicant_user_id
    role.accepted_at = utcnow()
    application.status = "accepted"
    application.reviewed_at = utcnow()

    db.session.commit()

    create_notification(
        application.applicant_user_id,
        "application_accepted",
        f"Accepted for {role.title}",
        f"You were accepted into {project.title}.",
        f"/my-projects/{project.id}/tasks",
    )
    db.session.commit()

    try:
        send_application_accepted(application.applicant, project, role)
    except Exception:
        pass

    check_mvt(project.id)

    flash(f"{application.applicant.full_name} has joined your team as {role.title}!", "success")
    return redirect(url_for("manage.manage_team", id=id))


@manage_bp.post("/<int:id>/team/decline/<int:app_id>")
@login_required
def decline_application(id, app_id):
    project = Project.query.get_or_404(id)
    _owner_or_403(project)

    application = RoleApplication.query.filter_by(id=app_id, project_id=id).first_or_404()
    message = strip_html(request.form.get("decline_message", ""), 1000)

    application.status = "declined"
    application.reviewed_at = utcnow()
    application.decline_message = message

    db.session.commit()

    create_notification(
        application.applicant_user_id,
        "application_declined",
        f"Update for {application.role.title}",
        f"Your application to {project.title} was declined.",
        f"/projects/{project.id}",
    )
    db.session.commit()

    try:
        send_application_declined(application.applicant, project, application.role, message)
    except Exception:
        pass

    flash("Application declined.", "info")
    return redirect(url_for("manage.manage_team", id=id))


@manage_bp.post("/<int:id>/launch")
@login_required
def launch_project(id):
    project = Project.query.get_or_404(id)
    _owner_or_403(project)

    if project.status not in {"launch_ready", "assembling"}:
        flash("Project cannot be launched from current status.", "warning")
        return redirect(url_for("manage.manage_dashboard", id=id))

    project.status = "active"
    db.session.commit()

    team_member_ids = {project.creator_user_id}
    team_member_ids.update(
        role.filled_by_user_id for role in project.roles if role.filled_by_user_id
    )

    from app.models import User

    for user_id in team_member_ids:
        create_notification(
            user_id,
            "project_launched",
            f"Project launched: {project.title}",
            "Your project is now active.",
            f"/my-projects/{project.id}/tasks",
        )
        user = User.query.get(user_id)
        if user:
            try:
                send_launch_notification(user, project)
            except Exception:
                pass

    db.session.commit()

    flash("Project is now active! Set up your tasks to get started.", "success")
    return redirect(url_for("tasks.board", id=id))
