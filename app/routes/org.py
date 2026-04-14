import logging
import traceback
from datetime import date, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError
from sqlalchemy.orm import joinedload

from app.extensions import db, limiter
from app.models import ChallengeSubmission, CivicChallenge, OrganizationAccount, Project, User
from app.routes import create_notification, subscription_required, validate_ajax_csrf
from app.services.ai_service import AIService
from app.services.email_service import send_challenge_status_update
from app.services.file_handler import generate_presigned_url
from app.services.project_search import build_project_query
from app.utils import strip_html, utcnow


org_bp = Blueprint("org", __name__, url_prefix="/org")
logger = logging.getLogger("quorum.routes")

SUBMISSION_STATUS_TRANSITIONS = {
    "submitted": {"under_review", "shortlisted"},
    "under_review": {"shortlisted"},
    "shortlisted": {"winner", "not_selected"},
    "winner": set(),
    "not_selected": set(),
}


def _org_profile_complete(org: OrganizationAccount | None) -> bool:
    if not org:
        return False

    required_values = [org.org_name, org.org_type, org.org_domain, org.mission_description]
    return all(bool((value or "").strip()) for value in required_values)


def _require_org_account():
    if current_user.account_type != "organization":
        flash("Organization tools are available for organization accounts only.", "warning")
        return None

    org = OrganizationAccount.query.filter_by(owner_user_id=current_user.id).first()
    if not _org_profile_complete(org):
        flash("Please complete your organization profile before using organization tools.", "warning")
        return None

    return org


def _redirect_for_org_setup():
    if current_user.account_type != "organization":
        return redirect(url_for("dashboard.home"))
    return redirect(url_for("settings.organization", next=request.path))


def _org_challenge_or_404(org: OrganizationAccount, challenge_id: int) -> CivicChallenge:
    return CivicChallenge.query.filter_by(id=challenge_id, org_id=org.id).first_or_404()


def _is_valid_submission_transition(current_status: str, next_status: str) -> bool:
    allowed = SUBMISSION_STATUS_TRANSITIONS.get(current_status, set())
    return next_status in allowed


@org_bp.get("/dashboard")
@login_required
def dashboard():
    org = _require_org_account()
    if not org:
        return _redirect_for_org_setup()

    projects_supported = Project.query.filter_by(org_support_id=org.id).all()
    active_challenges = CivicChallenge.query.filter_by(org_id=org.id).order_by(CivicChallenge.created_at.desc()).all()

    impact = {
        "projects_supported": len(projects_supported),
        "outcomes_achieved": len([project for project in projects_supported if project.status == "completed"]),
        "grants_disbursed_inr": sum((challenge.grant_amount_inr or 0) for challenge in active_challenges),
        "participants_engaged": sum(max(1, len(project.roles)) for project in projects_supported),
    }

    return render_template(
        "org/dashboard.html",
        org=org,
        projects_supported=projects_supported,
        active_challenges=active_challenges,
        today=date.today(),
        impact=impact,
    )


@org_bp.get("/discover")
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
def discover():
    org = _require_org_account()
    if not org:
        return _redirect_for_org_setup()

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
        return _redirect_for_org_setup()

    suggested_timeline_days = request.args.get("suggested_timeline_days", type=int)
    if suggested_timeline_days not in {30, 60, 90}:
        suggested_timeline_days = None

    prefill_deadline = strip_html(request.args.get("deadline", ""), 40).strip()
    if prefill_deadline:
        try:
            prefill_deadline = date.fromisoformat(prefill_deadline).isoformat()
        except ValueError:
            prefill_deadline = ""
    elif suggested_timeline_days:
        prefill_deadline = (date.today() + timedelta(days=suggested_timeline_days)).isoformat()

    query_prefill = {
        "title": strip_html(request.args.get("title", ""), 500),
        "description": strip_html(request.args.get("description", ""), 3000),
        "domain": strip_html(request.args.get("domain", org.org_domain or "community"), 100) or "community",
        "geographic_scope": strip_html(request.args.get("geographic_scope", "India"), 200) or "India",
        "grant_amount_inr": strip_html(request.args.get("grant_amount_inr", ""), 30).strip(),
        "deadline": prefill_deadline,
    }

    prefill_meta = {
        "from_ai": bool(query_prefill["title"] or query_prefill["description"]),
        "difficulty": strip_html(request.args.get("difficulty", ""), 50),
        "estimated_team_size": request.args.get("estimated_team_size", type=int),
        "suggested_timeline_days": suggested_timeline_days,
    }

    if request.method == "POST":
        if org.monthly_challenge_credits <= 0:
            flash("No challenge credits remaining this month.", "warning")
            return redirect(url_for("org.dashboard"))

        form_data = {
            "title": strip_html(request.form.get("title", ""), 500),
            "description": strip_html(request.form.get("description", ""), 3000),
            "domain": strip_html(request.form.get("domain", "community"), 100),
            "geographic_scope": strip_html(request.form.get("geographic_scope", "India"), 200),
            "grant_amount_inr": strip_html(request.form.get("grant_amount_inr", ""), 30).strip(),
            "deadline": strip_html(request.form.get("deadline", ""), 40).strip(),
        }

        try:
            grant_amount_inr = int(form_data["grant_amount_inr"] or 0)
        except ValueError:
            flash("Grant amount must be a valid number.", "danger")
            return render_template(
                "org/post_challenge.html",
                org=org,
                form_data=form_data,
                prefill_meta={"from_ai": False},
            )

        try:
            parsed_deadline = date.fromisoformat(form_data["deadline"]) if form_data["deadline"] else None
        except ValueError:
            flash("Please provide a valid deadline date.", "danger")
            return render_template(
                "org/post_challenge.html",
                org=org,
                form_data=form_data,
                prefill_meta={"from_ai": False},
            )

        challenge = CivicChallenge(
            org_id=org.id,
            title=form_data["title"],
            description=form_data["description"],
            domain=form_data["domain"],
            geographic_scope=form_data["geographic_scope"],
            grant_amount_inr=grant_amount_inr,
            deadline=parsed_deadline,
            status="open",
            created_at=utcnow(),
        )

        if not challenge.title or not challenge.description or not challenge.deadline:
            flash("Please fill in all required challenge fields.", "danger")
            return render_template(
                "org/post_challenge.html",
                org=org,
                form_data=form_data,
                prefill_meta={"from_ai": False},
            )

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

    return render_template("org/post_challenge.html", org=org, form_data=query_prefill, prefill_meta=prefill_meta)


@org_bp.route("/challenges/<int:id>/edit", methods=["GET", "POST"])
@login_required
@subscription_required(["org_starter", "org_team", "enterprise"])
def edit_challenge(id):
    org = _require_org_account()
    if not org:
        return _redirect_for_org_setup()

    challenge = _org_challenge_or_404(org, id)

    if request.method == "POST":
        title = strip_html(request.form.get("title", ""), 500)
        description = strip_html(request.form.get("description", ""), 3000)
        domain = strip_html(request.form.get("domain", "community"), 100)
        geographic_scope = strip_html(request.form.get("geographic_scope", "India"), 200)
        grant_amount_text = strip_html(request.form.get("grant_amount_inr", ""), 30).strip()
        deadline_text = strip_html(request.form.get("deadline", ""), 40).strip()

        try:
            grant_amount_inr = int(grant_amount_text or 0)
        except ValueError:
            flash("Grant amount must be a valid number.", "danger")
            return redirect(url_for("org.edit_challenge", id=challenge.id))

        try:
            parsed_deadline = date.fromisoformat(deadline_text) if deadline_text else None
        except ValueError:
            flash("Please provide a valid deadline date.", "danger")
            return redirect(url_for("org.edit_challenge", id=challenge.id))

        if not title or not description or not parsed_deadline:
            flash("Please fill in all required challenge fields.", "danger")
            return redirect(url_for("org.edit_challenge", id=challenge.id))

        challenge.title = title
        challenge.description = description
        challenge.domain = domain
        challenge.geographic_scope = geographic_scope
        challenge.grant_amount_inr = grant_amount_inr
        challenge.deadline = parsed_deadline

        db.session.commit()
        flash("Challenge updated.", "success")
        return redirect(url_for("org.challenge_detail", id=challenge.id))

    form_data = {
        "title": challenge.title,
        "description": challenge.description,
        "domain": challenge.domain,
        "geographic_scope": challenge.geographic_scope,
        "grant_amount_inr": challenge.grant_amount_inr or 0,
        "deadline": challenge.deadline.isoformat() if challenge.deadline else "",
    }

    return render_template(
        "org/post_challenge.html",
        org=org,
        form_data=form_data,
        prefill_meta={"from_ai": False},
        editing_challenge=challenge,
    )


@org_bp.get("/challenges/<int:id>")
@login_required
def challenge_detail(id):
    org = _require_org_account()
    if not org:
        return _redirect_for_org_setup()

    challenge = _org_challenge_or_404(org, id)
    submissions = (
        ChallengeSubmission.query.options(
            joinedload(ChallengeSubmission.submitter),
            joinedload(ChallengeSubmission.linked_project),
        )
        .filter(ChallengeSubmission.challenge_id == challenge.id)
        .order_by(ChallengeSubmission.submitted_at.desc())
        .all()
    )

    submissions_by_status = {
        "submitted": [],
        "under_review": [],
        "shortlisted": [],
        "winner": [],
        "not_selected": [],
    }

    for submission in submissions:
        if submission.proposal_document_path:
            submission.proposal_document_url = generate_presigned_url(submission.proposal_document_path)
        submissions_by_status.setdefault(submission.status, []).append(submission)

    total_submissions = len(submissions)
    days_remaining = (challenge.deadline - date.today()).days if challenge.deadline else None

    return render_template(
        "org/challenge_detail.html",
        challenge=challenge,
        submissions=submissions,
        submissions_by_status=submissions_by_status,
        total_submissions=total_submissions,
        days_remaining=days_remaining,
    )


@org_bp.post("/challenges/<int:challenge_id>/submissions/<int:submission_id>/status")
@login_required
def update_submission_status(challenge_id, submission_id):
    org = _require_org_account()
    if not org:
        return jsonify({"success": False, "error": "Organization account required."}), 403

    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    challenge = _org_challenge_or_404(org, challenge_id)
    submission = ChallengeSubmission.query.filter_by(
        id=submission_id,
        challenge_id=challenge.id,
    ).first_or_404()

    payload = request.get_json(silent=True) or {}
    requested_status = strip_html(payload.get("status", ""), 50).strip().lower()
    feedback = strip_html(payload.get("feedback", ""), 2000).strip()
    feedback_supplied = "feedback" in payload

    if feedback_supplied:
        submission.org_feedback = feedback or None

    if requested_status and requested_status != submission.status:
        if requested_status not in {"submitted", "under_review", "shortlisted", "winner", "not_selected"}:
            return jsonify({"success": False, "error": "Invalid submission status."}), 400

        if not _is_valid_submission_transition(submission.status, requested_status):
            return jsonify(
                {
                    "success": False,
                    "error": f"Invalid status transition: {submission.status} -> {requested_status}",
                }
            ), 400

        submission.status = requested_status
        submission.reviewed_at = utcnow()

        if requested_status == "winner":
            challenge.winner_submission_id = submission.id
            challenge.status = "awarded"
        elif challenge.winner_submission_id == submission.id:
            challenge.winner_submission_id = None

        create_notification(
            submission.submitter_user_id,
            "challenge_status_update",
            f"Submission update for {challenge.title}",
            f"Your submission is now marked as {requested_status.replace('_', ' ')}.",
            f"/challenges/{challenge.id}",
        )

        try:
            send_challenge_status_update(
                submission.submitter,
                challenge,
                requested_status,
                submission.org_feedback,
            )
        except Exception:
            pass

    db.session.commit()

    flash("Submission status updated.", "success")
    return jsonify(
        {
            "success": True,
            "new_status": submission.status,
            "feedback": submission.org_feedback or "",
        }
    )


@org_bp.post("/challenges/<int:id>/close")
@login_required
def close_challenge(id):
    org = _require_org_account()
    if not org:
        return _redirect_for_org_setup()

    challenge = _org_challenge_or_404(org, id)
    challenge.status = "closed"

    submissions = ChallengeSubmission.query.filter_by(challenge_id=challenge.id).all()
    for submission in submissions:
        create_notification(
            submission.submitter_user_id,
            "challenge_closed",
            f"Challenge closed: {challenge.title}",
            "The organization has completed challenge review. Check your submission status.",
            f"/challenges/{challenge.id}",
        )

        try:
            send_challenge_status_update(
                submission.submitter,
                challenge,
                submission.status,
                submission.org_feedback,
            )
        except Exception:
            pass

    db.session.commit()
    flash("Challenge closed and submitters notified.", "success")
    return redirect(url_for("org.dashboard"))


@org_bp.post("/challenges/<int:id>/delete")
@login_required
def delete_challenge(id):
    org = _require_org_account()
    if not org:
        return _redirect_for_org_setup()

    challenge = _org_challenge_or_404(org, id)
    if challenge.status != "open" or int(challenge.submission_count or 0) > 0:
        flash("Only open challenges with zero submissions can be deleted.", "warning")
        return redirect(url_for("org.challenge_detail", id=challenge.id))

    db.session.delete(challenge)
    db.session.commit()
    flash("Challenge deleted.", "success")
    return redirect(url_for("org.dashboard"))


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
        return _redirect_for_org_setup()

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
