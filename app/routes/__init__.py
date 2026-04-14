from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user
from flask_wtf.csrf import ValidationError, validate_csrf

from app.extensions import db
from app.models import Notification, Project, ProjectRole, RoleApplication
from app.utils import utcnow


def team_member_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        project_id = kwargs.get("id") or kwargs.get("project_id")
        project = Project.query.get_or_404(project_id)

        is_creator = project.creator_user_id == current_user.id
        is_member = is_project_team_member(project_id, current_user.id)

        if not (is_creator or is_member):
            abort(403)

        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated


def subscription_required(tiers):
    if isinstance(tiers, str):
        allowed = {tiers}
    else:
        allowed = set(tiers)

    def outer(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))

            if current_user.subscription_tier not in allowed:
                flash("Please upgrade your plan to access this feature.", "warning")
                return redirect(url_for("settings.billing"))

            return f(*args, **kwargs)

        return decorated

    return outer


def creator_required(project):
    if not current_user.is_authenticated:
        return False
    return project.creator_user_id == current_user.id


def is_project_team_member(project_id, user_id):
    if not user_id:
        return False

    # Primary source of truth for active team membership.
    has_filled_role = (
        ProjectRole.query.filter_by(
            project_id=project_id,
            filled_by_user_id=user_id,
            is_filled=True,
        ).first()
        is not None
    )
    if has_filled_role:
        return True

    # Fallback for historical rows where membership was approved but role flags were not synced.
    has_accepted_application = (
        RoleApplication.query.filter(
            RoleApplication.project_id == project_id,
            RoleApplication.applicant_user_id == user_id,
            RoleApplication.status.in_(["accepted", "approved"]),
        ).first()
        is not None
    )
    return has_accepted_application


def validate_ajax_csrf():
    token = request.headers.get("X-CSRFToken", "")
    if not token:
        raise ValidationError("Missing CSRF token")
    validate_csrf(token)


def create_notification(user_id, notification_type, title, message, link=None):
    note = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link=link,
        created_at=utcnow(),
    )
    db.session.add(note)
    return note
