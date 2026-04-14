import logging
import traceback
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import db, limiter
from app.forms.outcome_forms import OutcomeReportForm
from app.models import Project, ProjectOutcome, ProjectRole, Task, User
from app.routes import create_notification, validate_ajax_csrf
from app.services.ai_service import AIService
from app.services.email_service import send_completion_rating_prompt
from app.utils import strip_html, utcnow


outcomes_bp = Blueprint("outcomes", __name__, url_prefix="/my-projects/<int:id>/outcome")
logger = logging.getLogger("quorum.routes")


def _creator_or_403(project):
    if project.creator_user_id != current_user.id:
        from flask import abort

        abort(403)


@outcomes_bp.route("", methods=["GET", "POST"])
@login_required
def outcome_form(id):
    project = Project.query.get_or_404(id)
    _creator_or_403(project)

    if project.end_date and project.end_date > date.today() and request.args.get("force") != "1":
        flash("Outcome report can be submitted after end date or by using manual close.", "warning")
        return redirect(url_for("manage.manage_dashboard", id=id))

    existing = ProjectOutcome.query.filter_by(project_id=id).first()
    form = OutcomeReportForm(obj=existing)

    if form.validate_on_submit():
        outcome = existing or ProjectOutcome(project_id=id)
        outcome.outcome_achieved = strip_html(form.outcome_achieved.data)
        outcome.measurable_data = strip_html(form.measurable_data.data or "")
        outcome.team_size_actual = form.team_size_actual.data
        outcome.total_hours_estimated = form.total_hours_estimated.data
        outcome.unexpected_challenges = strip_html(form.unexpected_challenges.data)
        outcome.lessons_learned = strip_html(form.lessons_learned.data)
        outcome.would_recommend = bool(form.would_recommend.data)
        outcome.was_continued = bool(form.was_continued.data)
        outcome.continuation_description = strip_html(form.continuation_description.data or "")
        outcome.submitted_at = utcnow()
        outcome.is_published = False

        if not existing:
            db.session.add(outcome)

        project.status = "completed"
        db.session.commit()

        team_member_ids = {project.creator_user_id}
        team_member_ids.update(
            role.filled_by_user_id for role in ProjectRole.query.filter_by(project_id=id, is_filled=True).all() if role.filled_by_user_id
        )

        for user_id in team_member_ids:
            if user_id != current_user.id:
                create_notification(
                    user_id,
                    "project_completed",
                    f"Project completed: {project.title}",
                    "Submit your peer ratings for teammates.",
                    f"/projects/{project.id}/rate",
                )
                user = User.query.get(user_id)
                if user:
                    try:
                        send_completion_rating_prompt(user, project)
                    except Exception:
                        pass

        admin_users = User.query.filter_by(is_admin=True).all()
        for admin_user in admin_users:
            create_notification(
                admin_user.id,
                "outcome_review",
                f"Outcome report pending: {project.title}",
                "A new outcome report needs approval.",
                "/admin/outcomes",
            )

        db.session.commit()
        flash("Outcome submitted for review.", "success")
        return redirect(url_for("manage.manage_dashboard", id=id))

    pending_applications_count = len([app for app in project.applications if app.status == "pending"])
    overdue_tasks_count = (
        Task.query.filter_by(project_id=id)
        .filter(Task.status != "done", Task.due_date.isnot(None), Task.due_date < date.today())
        .count()
    )

    return render_template(
        "outcomes/form.html",
        project=project,
        form=form,
        existing=existing,
        active_tab="outcome",
        pending_applications_count=pending_applications_count,
        overdue_tasks_count=overdue_tasks_count,
    )


@outcomes_bp.post("/ai-assist")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_assist(id):
    method_name = "ai_assist"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id} | project_id={id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        project = Project.query.get_or_404(id)
        _creator_or_403(project)

        tasks_total = Task.query.filter_by(project_id=id).count()
        tasks_completed = Task.query.filter_by(project_id=id, status="done").count()

        milestones_data = []
        for milestone in project.milestones:
            tasks_done = sum(1 for task in (milestone.tasks or []) if task.status == "done")
            milestone_tasks_total = len(milestone.tasks or [])
            is_completed = bool(milestone.completed_at) or milestone.completion_pct >= 100
            if milestone_tasks_total > 0 and tasks_done == milestone_tasks_total:
                is_completed = True

            milestones_data.append(
                {
                    "title": milestone.title,
                    "completed": is_completed,
                    "tasks_done": tasks_done,
                    "tasks_total": milestone_tasks_total,
                }
            )

        team_size = 1 + ProjectRole.query.filter_by(project_id=id, is_filled=True).count()
        timeline_days = project.timeline_days or 60

        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"project_id={id} | tasks_completed={tasks_completed}/{tasks_total}"
        )

        result = AIService().generate_outcome_draft(
            project_title=project.title,
            domain=project.domain,
            milestones_data=milestones_data,
            tasks_completed=tasks_completed,
            tasks_total=tasks_total,
            team_size=team_size,
            timeline_days=timeline_days,
        )

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"result_keys={list(result.keys())}"
        )

        return jsonify(
            {
                "success": True,
                "outcome_draft": result.get("outcome_achieved", ""),
                "outcome_achieved": result.get("outcome_achieved", ""),
                "measurable_data_suggestions": result.get("measurable_data_suggestions", []),
                "lessons_learned_draft": result.get("lessons_learned_draft", ""),
                "unexpected_challenges_draft": result.get("unexpected_challenges_draft", ""),
                "completion_percentage": result.get("completion_percentage", 0),
            }
        )

    except Exception as error:
        logger.error(
            f"[ROUTE ERROR] {method_name} | user_id={user_id} | project_id={id} | "
            f"error_type={type(error).__name__} | message={str(error)}\n"
            f"traceback:\n{traceback.format_exc()}"
        )
        return jsonify(
            {
                "success": False,
                "error": "AI assistant is temporarily unavailable. Please try again.",
            }
        ), 500
