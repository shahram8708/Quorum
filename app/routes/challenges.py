import os
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError
from sqlalchemy import String, cast, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.extensions import db, limiter
from app.forms.challenge_forms import ChallengeSubmitForm
from app.models import ChallengeSubmission, CivicChallenge, Notification, OrganizationAccount, Project, User
from app.routes import validate_ajax_csrf
from app.services.ai_service import AIService
from app.services.email_service import (
    send_challenge_status_update,
    send_challenge_submission_confirmed,
    send_challenge_submission_received,
)
from app.services.file_handler import FileHandlerError, generate_presigned_url, upload_file_to_s3
from app.utils import strip_html, utcnow


challenges_bp = Blueprint("challenges", __name__, url_prefix="/challenges")

VALID_CHALLENGE_STATUSES = {"open", "closed", "awarded"}
VALID_SORTS = {"newest", "deadline", "grant_amount"}
ACTIVE_SUBMISSION_STATUSES = {"submitted", "under_review", "shortlisted"}


def _clean_text(value: str, max_len: int) -> str:
    return strip_html(value or "", max_len).strip()


def _challenge_filters_from_request() -> dict:
    return {
        "domain": _clean_text(request.args.get("domain", ""), 100).lower(),
        "status": _clean_text(request.args.get("status", ""), 50).lower(),
        "geo": _clean_text(request.args.get("geo", ""), 200),
        "sort": _clean_text(request.args.get("sort", "newest"), 40).lower() or "newest",
        "q": _clean_text(request.args.get("q", ""), 200),
    }


def _submission_status_label(value: str) -> str:
    return str(value or "submitted").replace("_", " ").title()


def _submission_format_label(value: str) -> str:
    mapping = {
        "project_link": "Project link",
        "proposal_doc": "Proposal document",
        "both": "Project link + proposal document",
    }
    return mapping.get(value or "project_link", "Project link")


def _parse_team_member_ids(raw_text: str) -> list[int]:
    usernames = []
    for line in (raw_text or "").splitlines():
        cleaned = _clean_text(line, 100).lower()
        if cleaned and cleaned not in usernames:
            usernames.append(cleaned)

    if not usernames:
        return []

    members = User.query.filter(func.lower(User.username).in_(usernames)).all()
    return [member.id for member in members if member.id != current_user.id]


def _load_user_projects(user_id: int) -> list[Project]:
    return (
        Project.query.filter(
            Project.creator_user_id == user_id,
            Project.is_published.is_(True),
            Project.status.in_(["assembling", "launch_ready", "active", "completed"]),
        )
        .order_by(Project.updated_at.desc())
        .all()
    )


def _enforce_submission_format(challenge: CivicChallenge, linked_project_id: int | None, has_document: bool, external_link: str) -> str | None:
    submission_format = challenge.submission_format or "project_link"
    has_project_reference = bool(linked_project_id or external_link)

    if submission_format == "proposal_doc" and not has_document:
        return "This challenge requires a proposal document upload."

    if submission_format == "project_link" and not has_project_reference:
        return "This challenge requires a linked project or an external demo/repository link."

    if submission_format == "both":
        if not has_document:
            return "This challenge requires a proposal document upload."
        if not has_project_reference:
            return "This challenge requires a linked project or an external demo/repository link."

    return None


def _challenge_is_open_for_submissions(challenge: CivicChallenge) -> bool:
    return challenge.status == "open" and challenge.deadline and challenge.deadline >= date.today()


@challenges_bp.get("")
def board():
    filters = _challenge_filters_from_request()
    query = CivicChallenge.query.options(joinedload(CivicChallenge.organization))

    if filters["domain"]:
        query = query.filter(CivicChallenge.domain == filters["domain"])

    if filters["status"] in VALID_CHALLENGE_STATUSES:
        query = query.filter(CivicChallenge.status == filters["status"])

    if filters["geo"]:
        query = query.filter(CivicChallenge.geographic_scope.ilike(f"%{filters['geo']}%"))

    if filters["q"]:
        keyword = f"%{filters['q']}%"
        query = query.filter(
            or_(
                CivicChallenge.title.ilike(keyword),
                CivicChallenge.description.ilike(keyword),
                cast(CivicChallenge.tags, String).ilike(keyword),
            )
        )

    sort_key = filters["sort"] if filters["sort"] in VALID_SORTS else "newest"
    if sort_key == "deadline":
        query = query.order_by(CivicChallenge.deadline.asc(), CivicChallenge.created_at.desc())
    elif sort_key == "grant_amount":
        query = query.order_by(CivicChallenge.grant_amount_inr.desc(), CivicChallenge.created_at.desc())
    else:
        query = query.order_by(CivicChallenge.created_at.desc())

    page = max(1, request.args.get("page", 1, type=int))
    pagination = query.paginate(page=page, per_page=9, error_out=False)

    featured_challenge = (
        CivicChallenge.query.options(joinedload(CivicChallenge.organization))
        .filter(CivicChallenge.status == "open")
        .order_by(CivicChallenge.grant_amount_inr.desc(), CivicChallenge.created_at.desc())
        .first()
    )

    return render_template(
        "challenges/board.html",
        pagination=pagination,
        featured_challenge=featured_challenge,
        filters=filters,
        today=date.today(),
    )


@challenges_bp.get("/<int:id>")
def detail(id):
    challenge = CivicChallenge.query.options(joinedload(CivicChallenge.organization)).get_or_404(id)

    if current_user.is_authenticated and current_user.account_type == "organization":
        org_account = OrganizationAccount.query.filter_by(owner_user_id=current_user.id).first()
        if org_account and challenge.org_id == org_account.id:
            return redirect(url_for("org.challenge_detail", id=challenge.id))

    db.session.execute(
        update(CivicChallenge)
        .where(CivicChallenge.id == challenge.id)
        .values(view_count=CivicChallenge.view_count + 1)
    )
    db.session.commit()

    challenge = CivicChallenge.query.options(joinedload(CivicChallenge.organization)).get_or_404(id)

    user_submission = None
    if current_user.is_authenticated:
        user_submission = ChallengeSubmission.query.filter_by(
            challenge_id=challenge.id,
            submitter_user_id=current_user.id,
        ).first()
        if user_submission and user_submission.proposal_document_path:
            user_submission.proposal_document_url = generate_presigned_url(user_submission.proposal_document_path)

    tag_conditions = []
    challenge_tags = challenge.tags if isinstance(challenge.tags, list) else []
    for tag in challenge_tags[:4]:
        clean_tag = _clean_text(str(tag), 50)
        if clean_tag:
            tag_conditions.append(Project.title.ilike(f"%{clean_tag}%"))
            tag_conditions.append(Project.problem_statement.ilike(f"%{clean_tag}%"))

    related_projects_query = Project.query.filter(Project.is_published.is_(True)).filter(
        or_(
            Project.org_support_id == challenge.org_id,
            Project.domain == challenge.domain,
            *tag_conditions,
        )
    )

    related_projects = (
        related_projects_query.order_by(Project.updated_at.desc()).limit(3).all()
        if tag_conditions
        else related_projects_query.order_by(Project.updated_at.desc()).limit(3).all()
    )

    return render_template(
        "challenges/detail.html",
        challenge=challenge,
        user_submission=user_submission,
        related_projects=related_projects,
        is_open_for_submission=_challenge_is_open_for_submissions(challenge),
        submission_format_label=_submission_format_label(challenge.submission_format),
        days_remaining=(challenge.deadline - date.today()).days if challenge.deadline else None,
        submission_status_label=_submission_status_label,
    )


@challenges_bp.route("/<int:id>/submit", methods=["GET", "POST"])
@login_required
def submit_solution(id):
    challenge = CivicChallenge.query.options(joinedload(CivicChallenge.organization)).get_or_404(id)

    if current_user.account_type == "organization":
        flash("Organization accounts cannot submit challenge solutions.", "warning")
        return redirect(url_for("challenges.detail", id=challenge.id))

    if not _challenge_is_open_for_submissions(challenge):
        flash("This challenge is no longer accepting submissions.", "warning")
        return redirect(url_for("challenges.detail", id=challenge.id))

    existing_submission = ChallengeSubmission.query.filter_by(
        challenge_id=challenge.id,
        submitter_user_id=current_user.id,
    ).first()
    if existing_submission:
        flash("You already submitted a solution for this challenge.", "warning")
        return redirect(url_for("challenges.detail", id=challenge.id))

    form = ChallengeSubmitForm()
    user_projects = _load_user_projects(current_user.id)
    form.linked_project_id.choices = [(0, "None")] + [(project.id, project.title) for project in user_projects]

    if form.validate_on_submit():
        linked_project_id = form.linked_project_id.data if form.linked_project_id.data else None
        if linked_project_id == 0:
            linked_project_id = None

        if linked_project_id and linked_project_id not in {project.id for project in user_projects}:
            flash("You can only link projects you own.", "danger")
            return render_template(
                "challenges/submit.html",
                challenge=challenge,
                form=form,
                user_projects=user_projects,
                days_remaining=(challenge.deadline - date.today()).days,
            )

        approach_summary = _clean_text(form.approach_summary.data, 1000)
        if len(approach_summary) < 100:
            flash("Approach summary must be at least 100 characters after sanitization.", "danger")
            return render_template(
                "challenges/submit.html",
                challenge=challenge,
                form=form,
                user_projects=user_projects,
                days_remaining=(challenge.deadline - date.today()).days,
            )

        external_link = _clean_text(form.external_link.data, 500)
        team_member_ids = _parse_team_member_ids(form.team_members_text.data or "")

        proposal_path = None
        proposal_url = None
        proposal_file = form.proposal_document.data

        has_document = bool(proposal_file and getattr(proposal_file, "filename", ""))
        format_error = _enforce_submission_format(challenge, linked_project_id, has_document, external_link)
        if format_error:
            flash(format_error, "danger")
            return render_template(
                "challenges/submit.html",
                challenge=challenge,
                form=form,
                user_projects=user_projects,
                days_remaining=(challenge.deadline - date.today()).days,
            )

        if has_document:
            proposal_file.stream.seek(0, os.SEEK_END)
            proposal_size = proposal_file.stream.tell()
            proposal_file.stream.seek(0)

            if proposal_size > 10 * 1024 * 1024:
                flash("Proposal document must be 10MB or smaller.", "danger")
                return render_template(
                    "challenges/submit.html",
                    challenge=challenge,
                    form=form,
                    user_projects=user_projects,
                    days_remaining=(challenge.deadline - date.today()).days,
                )

            try:
                proposal_path = upload_file_to_s3(
                    proposal_file,
                    f"challenge_proposal_{challenge.id}_{current_user.id}",
                    allowed_types={
                        "application/pdf",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    },
                )
                proposal_url = generate_presigned_url(proposal_path)
            except FileHandlerError as error:
                flash(str(error), "danger")
                return render_template(
                    "challenges/submit.html",
                    challenge=challenge,
                    form=form,
                    user_projects=user_projects,
                    days_remaining=(challenge.deadline - date.today()).days,
                )

        submission = ChallengeSubmission(
            challenge_id=challenge.id,
            submitter_user_id=current_user.id,
            team_name=_clean_text(form.team_name.data, 300),
            team_member_ids=team_member_ids,
            approach_summary=approach_summary,
            linked_project_id=linked_project_id,
            proposal_document_path=proposal_path,
            proposal_document_url=proposal_url,
            external_link=external_link or None,
            status="submitted",
            submitted_at=utcnow(),
        )

        challenge.submission_count = int(challenge.submission_count or 0) + 1

        org_owner = challenge.organization.owner if challenge.organization else None
        if org_owner:
            db.session.add(
                Notification(
                    user_id=org_owner.id,
                    notification_type="challenge_submission_received",
                    title=f"New submission: {challenge.title}",
                    message=f"{current_user.first_name} submitted \"{submission.team_name}\" to your challenge.",
                    link=url_for("org.challenge_detail", id=challenge.id),
                )
            )

        for member_id in team_member_ids:
            db.session.add(
                Notification(
                    user_id=member_id,
                    notification_type="challenge_team_update",
                    title=f"You were added to team {submission.team_name}",
                    message=f"{current_user.full_name} added you to a submission for {challenge.title}.",
                    link=url_for("challenges.detail", id=challenge.id),
                )
            )

        db.session.add(submission)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("You already submitted a solution for this challenge.", "warning")
            return redirect(url_for("challenges.detail", id=challenge.id))

        try:
            if org_owner:
                send_challenge_submission_received(org_owner, challenge, submission)
            send_challenge_submission_confirmed(current_user, challenge)
        except Exception:
            pass

        flash("Your solution has been submitted successfully.", "success")
        return redirect(url_for("challenges.detail", id=challenge.id))

    if form.is_submitted() and form.errors:
        for field_name, errors in form.errors.items():
            field = getattr(form, field_name, None)
            field_label = field.label.text if field is not None else field_name
            for error in errors:
                flash(f"{field_label}: {error}", "danger")

    return render_template(
        "challenges/submit.html",
        challenge=challenge,
        form=form,
        user_projects=user_projects,
        days_remaining=(challenge.deadline - date.today()).days,
    )


@challenges_bp.route("/submissions/<int:submission_id>/edit", methods=["GET", "POST"])
@login_required
def edit_submission(submission_id):
    submission = ChallengeSubmission.query.options(
        joinedload(ChallengeSubmission.challenge).joinedload(CivicChallenge.organization)
    ).filter_by(
        id=submission_id,
        submitter_user_id=current_user.id,
    ).first_or_404()

    challenge = submission.challenge
    if not challenge:
        flash("Challenge not found for this submission.", "danger")
        return redirect(url_for("challenges.my_submissions"))

    if submission.status != "submitted" or not _challenge_is_open_for_submissions(challenge):
        flash("Only open submitted entries can be edited.", "warning")
        return redirect(url_for("challenges.detail", id=challenge.id))

    form = ChallengeSubmitForm()
    user_projects = _load_user_projects(current_user.id)
    form.linked_project_id.choices = [(0, "None")] + [(project.id, project.title) for project in user_projects]

    if request.method == "GET":
        form.team_name.data = submission.team_name
        form.approach_summary.data = submission.approach_summary
        form.linked_project_id.data = submission.linked_project_id or 0
        form.external_link.data = submission.external_link or ""
        form.agree_terms.data = True

        usernames = []
        member_ids = submission.team_member_ids if isinstance(submission.team_member_ids, list) else []
        if member_ids:
            members = User.query.filter(User.id.in_(member_ids)).all()
            usernames = [member.username for member in members]
        form.team_members_text.data = "\n".join(usernames)

    if form.validate_on_submit():
        linked_project_id = form.linked_project_id.data if form.linked_project_id.data else None
        if linked_project_id == 0:
            linked_project_id = None

        if linked_project_id and linked_project_id not in {project.id for project in user_projects}:
            flash("You can only link projects you own.", "danger")
            return render_template(
                "challenges/submit.html",
                challenge=challenge,
                form=form,
                user_projects=user_projects,
                days_remaining=(challenge.deadline - date.today()).days,
            )

        approach_summary = _clean_text(form.approach_summary.data, 1000)
        if len(approach_summary) < 100:
            flash("Approach summary must be at least 100 characters after sanitization.", "danger")
            return render_template(
                "challenges/submit.html",
                challenge=challenge,
                form=form,
                user_projects=user_projects,
                days_remaining=(challenge.deadline - date.today()).days,
            )

        external_link = _clean_text(form.external_link.data, 500)
        team_member_ids = _parse_team_member_ids(form.team_members_text.data or "")

        proposal_path = submission.proposal_document_path
        proposal_url = submission.proposal_document_url
        proposal_file = form.proposal_document.data
        uploaded_new_document = bool(proposal_file and getattr(proposal_file, "filename", ""))
        has_document = bool(uploaded_new_document or proposal_path)

        format_error = _enforce_submission_format(challenge, linked_project_id, has_document, external_link)
        if format_error:
            flash(format_error, "danger")
            return render_template(
                "challenges/submit.html",
                challenge=challenge,
                form=form,
                user_projects=user_projects,
                days_remaining=(challenge.deadline - date.today()).days,
            )

        if uploaded_new_document:
            proposal_file.stream.seek(0, os.SEEK_END)
            proposal_size = proposal_file.stream.tell()
            proposal_file.stream.seek(0)

            if proposal_size > 10 * 1024 * 1024:
                flash("Proposal document must be 10MB or smaller.", "danger")
                return render_template(
                    "challenges/submit.html",
                    challenge=challenge,
                    form=form,
                    user_projects=user_projects,
                    days_remaining=(challenge.deadline - date.today()).days,
                )

            try:
                proposal_path = upload_file_to_s3(
                    proposal_file,
                    f"challenge_proposal_{challenge.id}_{current_user.id}",
                    allowed_types={
                        "application/pdf",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    },
                )
                proposal_url = generate_presigned_url(proposal_path)
            except FileHandlerError as error:
                flash(str(error), "danger")
                return render_template(
                    "challenges/submit.html",
                    challenge=challenge,
                    form=form,
                    user_projects=user_projects,
                    days_remaining=(challenge.deadline - date.today()).days,
                )

        submission.team_name = _clean_text(form.team_name.data, 300)
        submission.approach_summary = approach_summary
        submission.linked_project_id = linked_project_id
        submission.external_link = external_link or None
        submission.team_member_ids = team_member_ids
        submission.proposal_document_path = proposal_path
        submission.proposal_document_url = proposal_url

        db.session.commit()
        flash("Submission updated.", "success")
        return redirect(url_for("challenges.detail", id=challenge.id))

    if form.is_submitted() and form.errors:
        for field_name, errors in form.errors.items():
            field = getattr(form, field_name, None)
            field_label = field.label.text if field is not None else field_name
            for error in errors:
                flash(f"{field_label}: {error}", "danger")

    return render_template(
        "challenges/submit.html",
        challenge=challenge,
        form=form,
        user_projects=user_projects,
        days_remaining=(challenge.deadline - date.today()).days,
    )


@challenges_bp.get("/my-submissions")
@login_required
def my_submissions():
    status_filter = _clean_text(request.args.get("status", "all"), 40).lower() or "all"

    submissions_query = (
        ChallengeSubmission.query.options(
            joinedload(ChallengeSubmission.challenge).joinedload(CivicChallenge.organization),
            joinedload(ChallengeSubmission.linked_project),
        )
        .filter(ChallengeSubmission.submitter_user_id == current_user.id)
        .order_by(ChallengeSubmission.submitted_at.desc())
    )

    if status_filter != "all":
        submissions_query = submissions_query.filter(ChallengeSubmission.status == status_filter)

    submissions = submissions_query.all()
    for submission in submissions:
        if submission.proposal_document_path:
            submission.proposal_document_url = generate_presigned_url(submission.proposal_document_path)

    counts = {
        "all": ChallengeSubmission.query.filter_by(submitter_user_id=current_user.id).count(),
        "submitted": ChallengeSubmission.query.filter_by(submitter_user_id=current_user.id, status="submitted").count(),
        "under_review": ChallengeSubmission.query.filter_by(submitter_user_id=current_user.id, status="under_review").count(),
        "shortlisted": ChallengeSubmission.query.filter_by(submitter_user_id=current_user.id, status="shortlisted").count(),
        "winner": ChallengeSubmission.query.filter_by(submitter_user_id=current_user.id, status="winner").count(),
        "not_selected": ChallengeSubmission.query.filter_by(submitter_user_id=current_user.id, status="not_selected").count(),
    }

    active_submissions = [submission for submission in submissions if submission.status in ACTIVE_SUBMISSION_STATUSES]
    reviewed_submissions = [submission for submission in submissions if submission.status not in ACTIVE_SUBMISSION_STATUSES]

    return render_template(
        "challenges/my_submissions.html",
        submissions=submissions,
        active_submissions=active_submissions,
        reviewed_submissions=reviewed_submissions,
        counts=counts,
        status_filter=status_filter,
        today=date.today(),
        submission_status_label=_submission_status_label,
    )


@challenges_bp.post("/ai/generate-brief")
@login_required
@limiter.limit("10 per hour", key_func=lambda: str(current_user.id))
def generate_brief():
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 400

    payload = request.get_json(silent=True) or {}
    challenge_title = _clean_text(payload.get("challenge_title", ""), 300)
    challenge_description = _clean_text(payload.get("challenge_description", ""), 3000)
    domain = _clean_text(payload.get("domain", "community"), 120) or "community"

    if not challenge_title or not challenge_description:
        return jsonify({"success": False, "error": "Challenge title and description are required."}), 400

    brief = AIService().generate_submission_brief(challenge_title, challenge_description, domain)
    return jsonify({"success": True, "brief_suggestions": brief})
