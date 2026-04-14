import logging
import traceback

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import limiter
from app.models import ActionTemplate
from app.routes import validate_ajax_csrf
from app.services.ai_service import AIService
from app.utils import strip_html


templates_bp = Blueprint("templates", __name__, url_prefix="/templates")
logger = logging.getLogger("quorum.routes")


@templates_bp.get("")
def index():
    query = ActionTemplate.query.filter_by(is_published=True)

    domain = request.args.get("domain")
    quality_tier = request.args.get("quality_tier")

    if domain:
        query = query.filter_by(domain=domain)
    if quality_tier:
        query = query.filter_by(quality_tier=quality_tier)

    templates = query.order_by(ActionTemplate.updated_at.desc()).all()
    return render_template(
        "templates_lib/index.html",
        templates=templates,
        selected_domain=domain,
        selected_quality_tier=quality_tier,
    )


@templates_bp.get("/<int:id>")
def detail(id):
    template = ActionTemplate.query.get_or_404(id)
    related_templates = (
        ActionTemplate.query.filter_by(is_published=True, domain=template.domain)
        .filter(ActionTemplate.id != template.id)
        .order_by(ActionTemplate.updated_at.desc())
        .limit(6)
        .all()
    )
    return render_template("templates_lib/detail.html", template=template, related_templates=related_templates)


@templates_bp.post("/ai/search")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_search():
    method_name = "templates_ai_search"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        data = request.get_json(silent=True) or {}
        query_text = strip_html(data.get("query", ""), 300).strip()

        if not query_text:
            logger.warning(
                f"[ROUTE] {method_name} - missing query | user_id={user_id} | data={data}"
            )
            return jsonify({"success": False, "error": "Missing query in request body"}), 400

        if len(query_text) < 3:
            return jsonify(
                {
                    "success": False,
                    "error": "Please enter at least 3 characters for template search.",
                }
            ), 400

        templates = ActionTemplate.query.filter_by(is_published=True).all()
        templates_summary = [
            {
                "id": template.id,
                "title": template.title,
                "domain": template.domain,
                "problem_archetype": template.problem_archetype,
                "quality_tier": template.quality_tier,
            }
            for template in templates
        ]

        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"query_length={len(query_text)} | templates_count={len(templates_summary)}"
        )

        ai_result = AIService().ai_template_search(query_text, templates_summary)
        matched_ids = ai_result.get("matched_template_ids", [])
        match_explanations = ai_result.get("match_explanations", {})

        if not matched_ids:
            matched_ids = [template.id for template in templates[:8]]

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"matches_found={len(matched_ids)}"
        )

        return jsonify(
            {
                "success": True,
                "matched_template_ids": matched_ids,
                "match_explanations": match_explanations,
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


@templates_bp.get("/<int:id>/start")
@login_required
def start_from_template(id):
    template = ActionTemplate.query.get_or_404(id)
    session["template_seed"] = {
        "title": template.title,
        "domain": template.domain,
        "problem_archetype": template.problem_archetype,
        "recommended_team_size": template.recommended_team_size,
        "recommended_timeline_days": template.recommended_timeline_days,
        "recommended_roles": template.recommended_roles,
    }
    return redirect(url_for("create.start"))
