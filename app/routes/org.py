import logging
import traceback
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import db, limiter
from app.models import CivicChallenge, OrganizationAccount, Project, User
from app.routes import create_notification, subscription_required, validate_ajax_csrf
from app.services.ai_service import AIService
from app.services.project_search import build_project_query
from app.utils import strip_html, utcnow


org_bp = Blueprint("org", __name__, url_prefix="/org")
logger = logging.getLogger("quorum.routes")


def _require_org_account():
    org = OrganizationAccount.query.filter_by(owner_user_id=current_user.id).first()
    if not org:
        flash("Please complete your organization setup.", "warning")
        return None
    return org


@org_bp.get("/dashboard")
@login_required
def dashboard():
    org = _require_org_account()
    if not org:
        return redirect(url_for("settings.account"))

    projects_supported = Project.query.filter_by(org_support_id=org.id).all()
    challenges = CivicChallenge.query.filter_by(org_id=org.id).order_by(CivicChallenge.created_at.desc()).all()

    impact = {
        "projects_supported": len(projects_supported),
        "outcomes_achieved": len([project for project in projects_supported if project.status == "completed"]),
        "grants_disbursed_inr": sum((challenge.grant_amount_inr or 0) for challenge in challenges),
        "participants_engaged": sum(max(1, len(project.roles)) for project in projects_supported),
    }

    return render_template("org/dashboard.html", org=org, projects_supported=projects_supported, challenges=challenges, impact=impact)


@org_bp.get("/discover")
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
def discover():
    org = _require_org_account()
    if not org:
        return redirect(url_for("settings.account"))

    filters = {
        "domain": request.args.get("domain"),
        "status": request.args.get("status"),
        "geographic_scope": request.args.get("geographic_scope"),
        "keyword": request.args.get("keyword"),
        "sort": request.args.get("sort", "newest"),
    }
    projects = build_project_query(filters)

    return render_template("org/discover.html", org=org, projects=projects)


@org_bp.post("/discover/ai-challenges")
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
@limiter.limit("30 per hour", key_func=lambda: str(current_user.id))
def ai_challenges():
    method_name = "org_ai_challenges"
    user_id = getattr(current_user, "id", "unknown")

    try:
        validate_ajax_csrf()
    except ValidationError:
        logger.warning(f"[ROUTE] {method_name} - invalid CSRF token | user_id={user_id}")
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    try:
        payload = request.get_json(silent=True) or {}
        geography = strip_html(payload.get("geography", "India"), 200).strip() or "India"
        domain = strip_html(payload.get("domain", "community"), 100).strip() or "community"

        logger.info(
            f"[ROUTE] {method_name} called | user_id={user_id} | "
            f"geography={geography} | domain={domain}"
        )

        result = AIService().discover_civic_challenges(geography, domain)

        logger.info(
            f"[ROUTE] {method_name} success | user_id={user_id} | "
            f"challenges_count={len(result.get('challenges', []))}"
        )

        return jsonify(
            {
                "success": True,
                "challenges": result.get("challenges", []),
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


@org_bp.route("/challenges/post", methods=["GET", "POST"])
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
def post_challenge():
    org = _require_org_account()
    if not org:
        return redirect(url_for("settings.account"))

    if request.method == "POST":
        if org.monthly_challenge_credits <= 0:
            flash("No challenge credits remaining this month.", "warning")
            return redirect(url_for("org.dashboard"))

        challenge = CivicChallenge(
            org_id=org.id,
            title=strip_html(request.form.get("title", ""), 500),
            description=strip_html(request.form.get("description", ""), 3000),
            domain=strip_html(request.form.get("domain", "community"), 100),
            geographic_scope=strip_html(request.form.get("geographic_scope", "India"), 200),
            grant_amount_inr=int(request.form.get("grant_amount_inr", 0) or 0),
            deadline=request.form.get("deadline", type=lambda value: date.fromisoformat(value) if value else None),
            status="open",
            created_at=utcnow(),
        )

        if not challenge.title or not challenge.description or not challenge.deadline:
            flash("Please fill in all required challenge fields.", "danger")
            return render_template("org/post_challenge.html", org=org)

        db.session.add(challenge)
        org.monthly_challenge_credits -= 1

        interested_users = User.query.filter_by(is_open_to_projects=True, is_verified=True).limit(200).all()
        for user in interested_users:
            if challenge.domain in (user.domain_interests or []):
                create_notification(
                    user.id,
                    "new_challenge",
                    f"New Civic Challenge: {challenge.title}",
                    f"{org.org_name} posted a challenge in {challenge.domain}.",
                    f"/org/discover",
                )

        db.session.commit()
        flash("Challenge posted! Contributors will be notified.", "success")
        return redirect(url_for("org.dashboard"))

    return render_template("org/post_challenge.html", org=org)


@org_bp.post("/message/<int:project_id>")
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
def message_creator(project_id):
    project = Project.query.get_or_404(project_id)
    message_text = strip_html(request.form.get("message", "Your organization would like to connect."), 1000)

    create_notification(
        project.creator_user_id,
        "org_message",
        "Organization inquiry",
        message_text,
        f"/projects/{project.id}",
    )
    db.session.commit()
    flash("Message sent to project creator.", "success")
    return redirect(url_for("org.discover"))


@org_bp.route("/support/<int:project_id>", methods=["GET", "POST"])
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
def offer_support(project_id):
    project = Project.query.get_or_404(project_id)
    org = _require_org_account()
    if not org:
        return redirect(url_for("settings.account"))

    if request.method == "POST":
        project.org_support_id = org.id
        create_notification(
            project.creator_user_id,
            "org_support_offer",
            f"Support offer for {project.title}",
            "An organization offered support to your project.",
            f"/projects/{project.id}",
        )
        db.session.commit()
        flash("Support offer submitted.", "success")
        return redirect(url_for("org.discover"))

    return render_template("org/support_offer.html", project=project, org=org)
