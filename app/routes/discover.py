import logging
import traceback

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import limiter
from app.models import Project
from app.routes import validate_ajax_csrf
from app.services.ai_service import AIService
from app.services.project_search import build_project_query


discover_bp = Blueprint("discover", __name__, url_prefix="/discover")
logger = logging.getLogger("quorum.routes")


@discover_bp.get("")
@login_required
def index():
    filters = {
        "domain": request.args.get("domain"),
        "status": request.args.get("status"),
        "geographic_scope": request.args.get("geographic_scope"),
        "skills_needed": request.args.getlist("skills_needed"),
        "keyword": request.args.get("keyword"),
        "sort": request.args.get("sort", "newest"),
    }
    projects = build_project_query(filters, current_user if current_user.is_authenticated else None)
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 12
    total = len(projects)

    return render_template(
        "discover/index.html",
        projects=projects[(page - 1) * per_page : page * per_page],
        page=page,
        per_page=per_page,
        total=total,
        filters=filters,
        is_contributions=False,
    )


@discover_bp.get("/recommended")
@login_required
def recommended():
    recommended_projects = build_project_query({"sort": "highest_match"}, user=current_user)[:10]

    completed_projects = Project.query.filter_by(creator_user_id=current_user.id, status="completed").all()
    recommendation = AIService().personalized_recommendations(
        user_skills=[skill.name for skill in current_user.skills],
        user_domains=current_user.domain_interests or [],
        user_city=current_user.city,
        user_country=current_user.country,
        completed_project_titles=[project.title for project in completed_projects],
        available_hours_per_week=int(current_user.availability_hours or 3),
    )
    explanation = (
        f"{recommendation.get('recommendation_headline', '')} "
        f"{recommendation.get('recommendation_explanation', '')}"
    ).strip()

    return render_template(
        "discover/recommended.html",
        projects=recommended_projects,
        explanation=explanation,
    )


@discover_bp.post("/ai/recommend")
@login_required
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_recommend():
    method_name = "ai_recommend"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        payload = request.get_json(silent=True) or {}
        logger.info(f"[ROUTE] {method_name} called | user_id={user_id} | payload_keys={list(payload.keys())}")

        completed_projects = Project.query.filter_by(creator_user_id=current_user.id, status="completed").all()
        recommendation = AIService().personalized_recommendations(
            user_skills=[skill.name for skill in current_user.skills],
            user_domains=current_user.domain_interests or [],
            user_city=current_user.city,
            user_country=current_user.country,
            completed_project_titles=[project.title for project in completed_projects],
            available_hours_per_week=int(current_user.availability_hours or 3),
        )

        explanation = (
            f"{recommendation.get('recommendation_headline', '')} "
            f"{recommendation.get('recommendation_explanation', '')}"
        ).strip()

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"result_keys={list(recommendation.keys())}"
        )

        return jsonify(
            {
                "success": True,
                "explanation": explanation,
                "recommendation_headline": recommendation.get("recommendation_headline", ""),
                "recommendation_explanation": recommendation.get("recommendation_explanation", ""),
                "top_skill_matches": recommendation.get("top_skill_matches", []),
                "suggested_search_terms": recommendation.get("suggested_search_terms", []),
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
