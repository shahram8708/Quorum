import logging
import traceback
from datetime import date, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import db, limiter
from app.forms.project_forms import (
    WizardStep1Form,
    WizardStep2Form,
    WizardStep3Form,
    WizardStep4Form,
    WizardStep5Form,
    WizardStep6Form,
)
from app.models import Project, ProjectRole, Skill
from app.routes import create_notification, validate_ajax_csrf
from app.services.ai_service import AIService
from app.services.scoping_validator import validate_scope
from app.services.skill_matcher import find_matching_contributors
from app.utils import strip_html


create_bp = Blueprint("create", __name__, url_prefix="/projects/new")
logger = logging.getLogger("quorum.routes")


def _get_or_create_draft() -> Project:
    draft = (
        Project.query.filter_by(creator_user_id=current_user.id, status="draft", is_published=False)
        .order_by(Project.updated_at.desc())
        .first()
    )
    if draft:
        return draft

    draft = Project(
        creator_user_id=current_user.id,
        title="Untitled Project",
        problem_statement="",
        project_type="awareness",
        success_definition="",
        geographic_scope="city",
        domain="community",
        timeline_days=30,
        resources_needed=[],
        status="draft",
        is_published=False,
        min_viable_team_size=2,
    )
    db.session.add(draft)
    db.session.commit()
    return draft


def _step_for_project(project: Project) -> int:
    if not project.problem_statement or not project.title:
        return 1
    if not project.project_type:
        return 2
    if not project.success_definition:
        return 3
    if not project.roles:
        return 4
    if not project.timeline_days:
        return 5
    if not project.resources_needed:
        return 6
    return 6


@create_bp.get("")
@login_required
def start():
    draft = _get_or_create_draft()
    template_seed = session.pop("template_seed", None)
    if template_seed:
        _apply_template_seed(draft, template_seed)
    step = _step_for_project(draft)
    return redirect(url_for(f"create.step_{step}"))


def _apply_template_seed(project, seed):
    project.title = seed.get("title", project.title)
    project.domain = seed.get("domain", project.domain)
    project.problem_statement = seed.get("problem_archetype", project.problem_statement)
    project.timeline_days = seed.get("recommended_timeline_days", project.timeline_days)
    project.min_viable_team_size = seed.get("recommended_team_size", project.min_viable_team_size)
    project.project_type = seed.get("project_type", project.project_type)

    ProjectRole.query.filter_by(project_id=project.id).delete()
    for role in seed.get("recommended_roles", [])[:8]:
        db.session.add(
            ProjectRole(
                project_id=project.id,
                title=role.get("title", "Role"),
                description=role.get("description", ""),
                skill_tags=role.get("skill_tags", []),
                hours_per_week=float(role.get("hours_per_week", 4)),
                is_mvt_required=True,
            )
        )
    db.session.commit()


def _bounded_float(value, default=4.0, min_value=1.0, max_value=40.0):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def _collect_step4_roles_from_form(form_data):
    roles_payload = form_data.getlist("role_title")
    descriptions = form_data.getlist("role_description")
    skill_tags_list = form_data.getlist("role_skill_tags")
    hours_list = form_data.getlist("role_hours")
    mvt_required_list = form_data.getlist("role_is_mvt_required")

    roles = []
    for idx, title in enumerate(roles_payload[:8]):
        raw_description = descriptions[idx] if idx < len(descriptions) else ""
        raw_skills = skill_tags_list[idx] if idx < len(skill_tags_list) else ""
        raw_hours = hours_list[idx] if idx < len(hours_list) else 4
        raw_is_mvt_required = mvt_required_list[idx] if idx < len(mvt_required_list) else "true"

        skill_ids = [int(skill_id) for skill_id in str(raw_skills).split(",") if skill_id.strip().isdigit()]

        roles.append(
            {
                "title": strip_html(title or "", 300).strip(),
                "description": strip_html(raw_description or "", 1200).strip(),
                "skill_tags": skill_ids,
                "hours_per_week": _bounded_float(raw_hours, default=4.0),
                "is_mvt_required": str(raw_is_mvt_required).lower() == "true",
            }
        )

    return roles


def _collect_complete_roles_from_json(role_items):
    complete_roles = []
    for role in role_items[:8]:
        if not isinstance(role, dict):
            continue

        raw_title = role.get("title", "")
        raw_description = role.get("description", "")
        raw_skill_tags = role.get("skill_tags", "")

        title = strip_html(raw_title or "", 300).strip()
        description = strip_html(raw_description or "", 1200).strip()
        if not title:
            continue

        skill_ids = [int(skill_id) for skill_id in str(raw_skill_tags).split(",") if skill_id.strip().isdigit()]
        is_mvt_required = str(role.get("is_mvt_required", "true")).lower() in {"true", "1", "yes", "on"}

        complete_roles.append(
            {
                "title": title,
                "description": description,
                "skill_tags": skill_ids,
                "hours_per_week": _bounded_float(role.get("hours_per_week", 4), default=4.0),
                "is_mvt_required": is_mvt_required,
            }
        )

    return complete_roles


def _render_step_4(form, draft, posted_roles=None, posted_min_viable_team_size=None):
    skills = Skill.query.filter_by(is_active=True).order_by(Skill.name).all()
    completed_until = max(3, _step_for_project(draft) - 1)
    return render_template(
        "wizard/step_4.html",
        form=form,
        draft=draft,
        step=4,
        completed_until=completed_until,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
        skills=skills,
        posted_roles=posted_roles,
        posted_min_viable_team_size=posted_min_viable_team_size,
    )


@create_bp.route("/step/1", methods=["GET", "POST"])
@login_required
def step_1():
    draft = _get_or_create_draft()
    form = WizardStep1Form(obj=draft)

    if form.validate_on_submit():
        draft.title = strip_html(form.title.data, 500)
        draft.problem_statement = strip_html(form.problem_statement.data)
        draft.domain = form.domain.data
        draft.geographic_scope = form.geographic_scope.data
        draft.city = strip_html(form.city.data or "", 200)
        draft.country = strip_html(form.country.data or "", 100)
        draft.latitude = form.latitude.data
        draft.longitude = form.longitude.data
        db.session.commit()
        return redirect(url_for("create.step_2"))

    completed_until = max(0, _step_for_project(draft) - 1)
    return render_template(
        "wizard/step_1.html",
        form=form,
        draft=draft,
        step=1,
        completed_until=completed_until,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
    )


@create_bp.post("/ai/enhance-description")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_enhance_description():
    method_name = "ai_enhance_description"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        data = request.get_json(silent=True) or {}
        raw_text = strip_html(data.get("raw_text") or data.get("text") or "", 5000).strip()

        if not raw_text:
            logger.warning(
                f"[ROUTE] {method_name} - missing 'raw_text' in request | "
                f"user_id={user_id} | data={data}"
            )
            return jsonify({"success": False, "error": "Missing raw_text in request body"}), 400

        if len(raw_text) < 20:
            return jsonify(
                {
                    "success": False,
                    "error": "Please write at least 20 characters before enhancing.",
                }
            ), 400

        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"raw_text_length={len(raw_text)}"
        )

        ai = AIService()
        result = ai.enhance_project_description(raw_text)

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"result_keys={list(result.keys())}"
        )

        return jsonify(
            {
                "success": True,
                "enhanced_description": result.get("enhanced_description", raw_text),
                "key_points": result.get("key_points", []),
                "word_count": result.get("word_count", len(raw_text.split())),
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


@create_bp.route("/step/2", methods=["GET", "POST"])
@login_required
def step_2():
    draft = _get_or_create_draft()
    form = WizardStep2Form(obj=draft)

    if form.validate_on_submit():
        draft.project_type = form.project_type.data
        db.session.commit()
        return redirect(url_for("create.step_3"))

    completed_until = max(1, _step_for_project(draft) - 1)
    return render_template(
        "wizard/step_2.html",
        form=form,
        draft=draft,
        step=2,
        completed_until=completed_until,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
    )


@create_bp.route("/step/3", methods=["GET", "POST"])
@login_required
def step_3():
    draft = _get_or_create_draft()
    form = WizardStep3Form(obj=draft)

    if form.validate_on_submit():
        draft.success_definition = strip_html(form.success_definition.data)

        local_validation = validate_scope(draft.success_definition, draft.timeline_days or 30)
        ai_result = AIService().validate_project_scope(draft.success_definition, draft.timeline_days or 30, draft.project_type)

        db.session.commit()

        if not local_validation["is_valid"] or not ai_result.get("is_appropriate", True):
            warning_message = local_validation.get("message") or ai_result.get("feedback")
            if warning_message:
                flash(warning_message, "warning")

        return redirect(url_for("create.step_4"))

    completed_until = max(2, _step_for_project(draft) - 1)
    return render_template(
        "wizard/step_3.html",
        form=form,
        draft=draft,
        step=3,
        completed_until=completed_until,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
    )


@create_bp.post("/ai/validate-scope")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_validate_scope():
    method_name = "ai_validate_scope"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        payload = request.get_json(silent=True) or {}
        success_definition = strip_html(payload.get("success_definition", ""), 5000).strip()
        project_type = strip_html(payload.get("project_type", "awareness"), 100).strip() or "awareness"

        if not success_definition:
            logger.warning(
                f"[ROUTE] {method_name} - missing success_definition | "
                f"user_id={user_id} | payload={payload}"
            )
            return jsonify({"success": False, "error": "Missing success_definition in request body"}), 400

        if len(success_definition) < 20:
            return jsonify(
                {
                    "success": False,
                    "error": "Please write at least 20 characters in the success definition.",
                }
            ), 400

        try:
            timeline_days = int(payload.get("timeline_days", 60))
        except (TypeError, ValueError):
            timeline_days = 60

        if timeline_days not in {30, 60, 90}:
            timeline_days = 60

        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"timeline_days={timeline_days} | project_type={project_type}"
        )

        ai_result = AIService().validate_project_scope(success_definition, timeline_days, project_type)

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"result_keys={list(ai_result.keys())}"
        )

        return jsonify(
            {
                "success": True,
                "is_valid": bool(ai_result.get("is_appropriate", True)),
                "scope_rating": ai_result.get("scope_rating", "appropriate"),
                "feedback": ai_result.get("feedback", ""),
                "score": ai_result.get("score", 5),
                "suggestions": ai_result.get("suggestions", []),
                "example_refined_definition": ai_result.get("example_refined_definition", ""),
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


@create_bp.route("/step/4", methods=["GET", "POST"])
@login_required
def step_4():
    draft = _get_or_create_draft()
    form = WizardStep4Form()

    if request.method == "GET":
        form.min_viable_team_size.data = draft.min_viable_team_size
        return _render_step_4(form, draft)

    posted_roles = _collect_step4_roles_from_form(request.form)
    posted_min_viable_team_size = request.form.get("min_viable_team_size", "").strip()

    if not form.validate_on_submit():
        return _render_step_4(
            form,
            draft,
            posted_roles=posted_roles,
            posted_min_viable_team_size=posted_min_viable_team_size,
        )

    if len(posted_roles) < 2:
        flash("At least two roles are required.", "danger")
        return _render_step_4(
            form,
            draft,
            posted_roles=posted_roles,
            posted_min_viable_team_size=posted_min_viable_team_size,
        )

    incomplete_indexes = [
        str(idx + 1)
        for idx, role in enumerate(posted_roles)
        if not role["title"]
    ]
    if incomplete_indexes:
        flash(
            "Each role needs a title. Incomplete role rows: "
            + ", ".join(incomplete_indexes[:5]),
            "danger",
        )
        return _render_step_4(
            form,
            draft,
            posted_roles=posted_roles,
            posted_min_viable_team_size=posted_min_viable_team_size,
        )

    draft.min_viable_team_size = form.min_viable_team_size.data

    ProjectRole.query.filter_by(project_id=draft.id).delete()
    for role_data in posted_roles:
        db.session.add(
            ProjectRole(
                project_id=draft.id,
                title=role_data["title"],
                description=role_data["description"],
                skill_tags=role_data["skill_tags"],
                hours_per_week=role_data["hours_per_week"],
                is_mvt_required=role_data["is_mvt_required"],
            )
        )

    db.session.commit()
    return redirect(url_for("create.step_5"))


@create_bp.post("/ai/suggest-roles")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_suggest_roles():
    method_name = "ai_suggest_roles"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        payload = request.get_json(silent=True) or {}
        draft = _get_or_create_draft()

        project_type = strip_html(
            payload.get("project_type") or draft.project_type or "awareness",
            100,
        ).strip() or "awareness"
        domain = strip_html(payload.get("domain") or draft.domain or "community", 100).strip() or "community"
        problem_statement = strip_html(
            payload.get("problem_statement") or draft.problem_statement or "",
            5000,
        ).strip()

        if not problem_statement:
            logger.warning(
                f"[ROUTE] {method_name} - missing problem_statement | "
                f"user_id={user_id} | payload={payload}"
            )
            return jsonify({"success": False, "error": "Missing problem_statement in request body"}), 400

        if len(problem_statement) < 20:
            return jsonify(
                {
                    "success": False,
                    "error": "Please write at least 20 characters before requesting role suggestions.",
                }
            ), 400

        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"project_type={project_type} | domain={domain}"
        )

        result = AIService().suggest_project_roles(project_type, domain, problem_statement)

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"roles_count={len(result.get('suggested_roles', []))}"
        )

        return jsonify(
            {
                "success": True,
                "suggested_roles": result.get("suggested_roles", []),
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


@create_bp.route("/step/5", methods=["GET", "POST"])
@login_required
def step_5():
    draft = _get_or_create_draft()
    form = WizardStep5Form()

    if request.method == "GET":
        form.timeline_days.data = str(draft.timeline_days or 30)
        form.start_date.data = draft.start_date or date.today()

    if form.validate_on_submit():
        draft.start_date = form.start_date.data

        if form.timeline_days.data == "custom" and form.custom_end_date.data:
            draft.end_date = form.custom_end_date.data
            draft.timeline_days = max((draft.end_date - draft.start_date).days, 1)
        else:
            draft.timeline_days = int(form.timeline_days.data)
            draft.end_date = draft.start_date + timedelta(days=draft.timeline_days)

        db.session.commit()
        return redirect(url_for("create.step_6"))

    completed_until = max(4, _step_for_project(draft) - 1)
    return render_template(
        "wizard/step_5.html",
        form=form,
        draft=draft,
        step=5,
        completed_until=completed_until,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
    )


@create_bp.route("/step/6", methods=["GET", "POST"])
@login_required
def step_6():
    draft = _get_or_create_draft()
    form = WizardStep6Form()

    if request.method == "GET":
        form.resources_needed.data = ", ".join(draft.resources_needed or [])
        form.estimated_budget.data = draft.estimated_budget

    if form.validate_on_submit():
        resources_raw = strip_html(form.resources_needed.data or "", 2000)
        draft.resources_needed = [item.strip() for item in resources_raw.split(",") if item.strip()]
        draft.estimated_budget = strip_html(form.estimated_budget.data or "", 100)
        db.session.commit()
        return redirect(url_for("create.preview"))

    completed_until = max(5, _step_for_project(draft) - 1)
    return render_template(
        "wizard/step_6.html",
        form=form,
        draft=draft,
        step=6,
        completed_until=completed_until,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
    )


@create_bp.post("/auto-save")
@login_required
def auto_save():
    draft = _get_or_create_draft()
    payload = request.json or {}

    if payload.get("problem_statement"):
        draft.problem_statement = strip_html(payload["problem_statement"], 4000)
    if payload.get("success_definition"):
        draft.success_definition = strip_html(payload["success_definition"], 3000)

    if payload.get("min_viable_team_size") is not None:
        try:
            min_team_size = int(payload.get("min_viable_team_size"))
            if 1 <= min_team_size <= 20:
                draft.min_viable_team_size = min_team_size
        except (TypeError, ValueError):
            pass

    roles_payload = payload.get("roles")
    if isinstance(roles_payload, list):
        complete_roles = _collect_complete_roles_from_json(roles_payload)
        if complete_roles:
            ProjectRole.query.filter_by(project_id=draft.id).delete()
            for role_data in complete_roles:
                db.session.add(
                    ProjectRole(
                        project_id=draft.id,
                        title=role_data["title"],
                        description=role_data["description"],
                        skill_tags=role_data["skill_tags"],
                        hours_per_week=role_data["hours_per_week"],
                        is_mvt_required=role_data["is_mvt_required"],
                    )
                )

    db.session.commit()
    return jsonify({"success": True})


@create_bp.get("/preview")
@login_required
def preview():
    draft = _get_or_create_draft()
    return render_template(
        "wizard/preview.html",
        draft=draft,
        step=6,
        completed_until=6,
        minimal_nav_mode=True,
        minimal_nav_label="My Projects",
        minimal_nav_link=url_for("manage.my_projects"),
    )


@create_bp.post("/save-draft")
@login_required
def save_draft():
    _get_or_create_draft()
    db.session.commit()
    flash("Draft saved. You can continue editing anytime.", "info")
    return redirect(url_for("manage.my_projects"))


@create_bp.post("/publish")
@login_required
def publish():
    draft = _get_or_create_draft()

    if not current_user.is_verified:
        flash("Please verify your email before publishing projects.", "warning")
        return redirect(url_for("auth.verify_pending"))

    draft.is_published = True
    draft.status = "assembling"
    db.session.commit()

    matches = find_matching_contributors(draft.id)
    for users in matches.values():
        for user in users:
            create_notification(
                user.id,
                "new_project_match",
                f"A project matches your skills: {draft.title}",
                "You have been invited to explore an open role.",
                f"/projects/{draft.id}",
            )

    db.session.commit()

    flash("Project is live! Notifying matching contributors.", "success")
    return redirect(url_for("manage.manage_dashboard", id=draft.id))
