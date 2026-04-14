import logging
import traceback

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import db, limiter
from app.models import AICivicPulseCache, Notification, Project, ProjectRole, RoleApplication
from app.routes import validate_ajax_csrf
from app.services.ai_service import AIService, format_civic_pulse_content
from app.services.project_search import build_project_query
from app.utils import utcnow


dashboard_bp = Blueprint("dashboard", __name__)
logger = logging.getLogger("quorum.routes")


@dashboard_bp.get("/dashboard")
@login_required
def home():
    creator_projects = Project.query.filter_by(creator_user_id=current_user.id).all()

    member_project_ids = [
        role.project_id
        for role in ProjectRole.query.filter_by(filled_by_user_id=current_user.id, is_filled=True).all()
    ]
    member_projects = Project.query.filter(Project.id.in_(member_project_ids)).all() if member_project_ids else []

    pending_applications = (
        RoleApplication.query.join(Project, RoleApplication.project_id == Project.id)
        .filter(Project.creator_user_id == current_user.id, RoleApplication.status == "pending")
        .all()
    )

    pulse_cache = AICivicPulseCache.query.filter_by(user_id=current_user.id).first()
    if not pulse_cache:
        logger.info(
            f"[ROUTE] dashboard_home fetching civic pulse | user_id={current_user.id} | "
            f"city={current_user.city}"
        )
        pulse_data = AIService().fetch_civic_pulse(
            current_user.city,
            current_user.country,
            current_user.domain_interests or [],
        )
        content = format_civic_pulse_content(pulse_data)
        pulse_cache = AICivicPulseCache(user_id=current_user.id, content=content, generated_at=utcnow())
        db.session.add(pulse_cache)
        db.session.commit()

    recommendations = build_project_query({"sort": "highest_match"}, user=current_user)[:3]
    recent_notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "dashboard/main.html",
        creator_projects=creator_projects,
        member_projects=member_projects,
        pending_applications=pending_applications,
        pulse_cache=pulse_cache,
        recommendations=recommendations,
        recent_notifications=recent_notifications,
    )


@dashboard_bp.get("/contributions")
@login_required
def contributions():
    role_entries = ProjectRole.query.filter_by(filled_by_user_id=current_user.id, is_filled=True).all()
    projects = [entry.project for entry in role_entries if entry.project]
    active_projects = [project for project in projects if project.status in {"assembling", "launch_ready", "active"}]
    completed_projects = [project for project in projects if project.status == "completed"]
    return render_template(
        "discover/index.html",
        projects=active_projects,
        completed_projects=completed_projects,
        is_contributions=True,
        page=1,
        per_page=len(active_projects) if active_projects else 1,
        total=len(active_projects),
        filters={},
    )


@dashboard_bp.get("/notifications")
@login_required
def notifications_index():
    page = max(1, request.args.get("page", 1, type=int))
    pagination = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    return render_template("dashboard/notifications.html", pagination=pagination)


@dashboard_bp.post("/notifications/<int:id>/read")
@login_required
def notification_read(id):
    note = Notification.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    note.is_read = True
    db.session.commit()
    return jsonify({"success": True})


@dashboard_bp.post("/notifications/mark-all-read")
@login_required
def notifications_mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json":
        return jsonify({"success": True})

    flash("All notifications marked as read.", "info")
    return redirect(url_for("dashboard.notifications_index"))


@dashboard_bp.post("/dashboard/ai/civic-pulse")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_civic_pulse():
    method_name = "ai_civic_pulse"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"city={current_user.city} | country={current_user.country}"
        )

        pulse_data = AIService().fetch_civic_pulse(
            current_user.city,
            current_user.country,
            current_user.domain_interests or [],
        )
        content = format_civic_pulse_content(pulse_data)

        cache = AICivicPulseCache.query.filter_by(user_id=current_user.id).first()
        if not cache:
            cache = AICivicPulseCache(user_id=current_user.id, content=content, generated_at=utcnow())
            db.session.add(cache)
        else:
            cache.content = content
            cache.generated_at = utcnow()
        db.session.commit()

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"stories_count={len(pulse_data.get('civic_stories', []))}"
        )

        return jsonify(
            {
                "success": True,
                "content": content,
                "overall_summary": pulse_data.get("overall_summary", ""),
                "civic_stories": pulse_data.get("civic_stories", []),
                "last_updated": pulse_data.get("last_updated", ""),
            }
        )

    except Exception as error:
        logger.error(
            f"[ROUTE ERROR] {method_name} | user_id={user_id} | "
            f"error_type={type(error).__name__} | message={str(error)}\n"
            f"traceback:\n{traceback.format_exc()}"
        )
        return jsonify(
            {
                "success": False,
                "error": "AI assistant is temporarily unavailable. Please try again.",
            }
        ), 500
