from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db, limiter
from app.forms.outcome_forms import PeerRatingForm
from app.models import PeerRating, Project, ProjectRole, RoleApplication
from app.routes import create_notification, is_project_team_member
from app.services.email_service import send_application_received
from app.services.project_search import build_project_query
from app.services.reputation_engine import recompute_reputation
from app.utils import strip_html, utcnow


projects_public_bp = Blueprint("projects_public", __name__, url_prefix="/projects")


def _already_applied_message(project_title, role_title):
    return (
        f"You already applied to {project_title} for the {role_title} role. "
        "Duplicate applications are not allowed."
    )


@projects_public_bp.get("")
def board():
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
    start = (page - 1) * per_page
    end = start + per_page
    items = projects[start:end]

    if request.headers.get("Accept") == "application/json" or request.args.get("format") == "json":
        return jsonify(
            {
                "items": [
                    {
                        "id": project.id,
                        "title": project.title,
                        "domain": project.domain,
                        "city": project.city,
                        "country": project.country,
                        "status": project.status,
                    }
                    for project in items
                ],
                "total": total,
                "page": page,
            }
        )

    return render_template("projects/public_board.html", projects=items, page=page, total=total, per_page=per_page)


@projects_public_bp.get("/<int:id>")
def detail(id):
    project = Project.query.get_or_404(id)
    open_roles = [role for role in project.roles if not role.is_filled]
    feed_posts = project.feed_posts[:8]
    user_applications_by_role_id = {}
    is_creator = False
    is_member = False
    can_rate_peers = False
    can_view_peer_ratings = False

    if current_user.is_authenticated:
        is_creator = current_user.id == project.creator_user_id
        is_member = (not is_creator) and is_project_team_member(project.id, current_user.id)
        if open_roles:
            open_role_ids = [role.id for role in open_roles]
            existing_applications = (
                RoleApplication.query.filter(
                    RoleApplication.applicant_user_id == current_user.id,
                    RoleApplication.role_id.in_(open_role_ids),
                )
                .all()
            )
            user_applications_by_role_id = {
                application.role_id: application
                for application in existing_applications
            }

        if project.status == "completed" and (is_creator or is_member):
            rate_targets = {
                role.filled_by_user_id
                for role in project.roles
                if role.filled_by_user_id and role.filled_by_user_id != current_user.id
            }
            if project.creator_user_id != current_user.id:
                rate_targets.add(project.creator_user_id)
            can_rate_peers = bool(rate_targets)
            can_view_peer_ratings = True

    return render_template(
        "projects/detail.html",
        project=project,
        open_roles=open_roles,
        feed_posts=feed_posts,
        user_applications_by_role_id=user_applications_by_role_id,
        is_creator=is_creator,
        is_member=is_member,
        can_rate_peers=can_rate_peers,
        can_view_peer_ratings=can_view_peer_ratings,
    )


@projects_public_bp.route("/<int:id>/apply/<int:role_id>", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per day", key_func=lambda: str(current_user.id), methods=["POST"])
def apply_role(id, role_id):
    project = Project.query.get_or_404(id)
    role = ProjectRole.query.filter_by(id=role_id, project_id=id).first_or_404()

    if current_user.id == project.creator_user_id:
        flash("Project creators cannot apply to roles in their own project.", "warning")
        return redirect(url_for("projects_public.detail", id=id))

    if role.is_filled:
        flash("This role is already filled.", "warning")
        return redirect(url_for("projects_public.detail", id=id))

    existing = RoleApplication.query.filter_by(
        project_id=id,
        role_id=role_id,
        applicant_user_id=current_user.id,
    ).first()
    if existing:
        flash("You already applied for this role.", "warning")
        return redirect(url_for("projects_public.detail", id=id))

    if request.method == "POST":
        text = strip_html(request.form.get("application_text", ""), 500)
        if not text:
            flash("Application message is required.", "danger")
            return render_template("projects/apply_role.html", project=project, role=role)

        application = RoleApplication(
            role_id=role.id,
            project_id=project.id,
            applicant_user_id=current_user.id,
            application_text=text,
            status="pending",
            applied_at=utcnow(),
        )
        db.session.add(application)

        create_notification(
            project.creator_user_id,
            "application_received",
            f"New application for {role.title}",
            f"{current_user.full_name} applied to {project.title}.",
            f"/my-projects/{project.id}/team",
        )

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("You already applied for this role.", "warning")
            return redirect(url_for("projects_public.detail", id=id))

        try:
            send_application_received(project.creator, current_user, project, role)
        except Exception:
            pass

        flash("Application submitted! The creator will review it soon.", "success")
        return redirect(url_for("projects_public.detail", id=id))

    return render_template("projects/apply_role.html", project=project, role=role)


@projects_public_bp.route("/<int:id>/rate", methods=["GET", "POST"])
@login_required
def rate_peers(id):
    project = Project.query.get_or_404(id)
    if project.status != "completed":
        flash("Peer ratings are available after project completion.", "warning")
        return redirect(url_for("projects_public.detail", id=id))

    is_team_member = (
        project.creator_user_id == current_user.id
        or is_project_team_member(project.id, current_user.id)
    )
    if not is_team_member:
        flash("Only verified team members can rate peers.", "danger")
        return redirect(url_for("projects_public.detail", id=id))

    teammates = [
        role.filled_by_user
        for role in project.roles
        if role.filled_by_user_id and role.filled_by_user_id != current_user.id
    ]
    if project.creator_user_id != current_user.id:
        teammates.append(project.creator)

    teammate_map = {user.id: user for user in teammates if user}
    form = PeerRatingForm()
    teammate_values = list(teammate_map.values())

    if request.method == "GET" and not teammate_values:
        flash("There are no teammates available to rate for this project.", "info")
        return redirect(url_for("projects_public.project_ratings", id=id))

    if request.method == "POST":
        if not form.validate_on_submit():
            flash("Could not submit ratings. Please refresh the page and try again.", "danger")
            return render_template("projects/rate_peers.html", project=project, teammates=teammate_values, form=form)

        ratings_to_add = []
        validation_errors = []
        valid_rating_values = {"1", "2", "3", "4", "5"}

        for teammate_id in request.form.getlist("rated_user_ids"):
            try:
                rated_id = int(teammate_id)
            except (TypeError, ValueError):
                continue

            if rated_id not in teammate_map:
                continue

            existing = PeerRating.query.filter_by(
                project_id=project.id,
                rater_user_id=current_user.id,
                rated_user_id=rated_id,
            ).first()
            if existing:
                continue

            score_fields = {
                "follow_through": request.form.get(f"follow_through_{rated_id}", "").strip(),
                "collaboration": request.form.get(f"collaboration_{rated_id}", "").strip(),
                "quality": request.form.get(f"quality_{rated_id}", "").strip(),
            }
            invalid_metrics = [
                metric.replace("_", " ").title()
                for metric, value in score_fields.items()
                if value not in valid_rating_values
            ]
            if invalid_metrics:
                validation_errors.append(
                    f"{teammate_map[rated_id].full_name}: {', '.join(invalid_metrics)} must be between 1 and 5."
                )
                continue

            ratings_to_add.append(
                PeerRating(
                    project_id=project.id,
                    rater_user_id=current_user.id,
                    rated_user_id=rated_id,
                    follow_through=int(score_fields["follow_through"]),
                    collaboration=int(score_fields["collaboration"]),
                    quality=int(score_fields["quality"]),
                    testimonial=strip_html(request.form.get(f"testimonial_{rated_id}", ""), 1000),
                    created_at=utcnow(),
                )
            )

        if validation_errors:
            for message in validation_errors[:3]:
                flash(message, "danger")
            if len(validation_errors) > 3:
                flash("Please correct the remaining teammate ratings and submit again.", "danger")
            return render_template("projects/rate_peers.html", project=project, teammates=teammate_values, form=form)

        if not ratings_to_add:
            flash("No new teammate ratings were submitted.", "info")
            return redirect(url_for("projects_public.project_ratings", id=id))

        db.session.add_all(ratings_to_add)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Some ratings were already submitted. Please refresh and try again.", "warning")
            return redirect(url_for("projects_public.rate_peers", id=id))

        for teammate in teammate_map.values():
            recompute_reputation(teammate.id)

        flash("Thank you for rating your teammates! Your track record has been updated.", "success")
        return redirect(url_for("projects_public.project_ratings", id=id))

    return render_template("projects/rate_peers.html", project=project, teammates=teammate_values, form=form)


@projects_public_bp.get("/<int:id>/ratings")
@login_required
def project_ratings(id):
    project = Project.query.get_or_404(id)
    if project.status != "completed":
        flash("Peer ratings are available after project completion.", "warning")
        return redirect(url_for("projects_public.detail", id=id))

    is_team_member = (
        project.creator_user_id == current_user.id
        or is_project_team_member(project.id, current_user.id)
    )
    if not is_team_member:
        flash("Only verified team members can view peer ratings.", "danger")
        return redirect(url_for("projects_public.detail", id=id))

    team_map = {}
    if project.creator:
        team_map[project.creator.id] = project.creator
    for role in project.roles:
        if role.filled_by_user:
            team_map[role.filled_by_user.id] = role.filled_by_user

    ratings = (
        PeerRating.query.filter_by(project_id=project.id)
        .order_by(PeerRating.created_at.desc())
        .all()
    )

    summary_map = {
        user_id: {
            "user": user,
            "count": 0,
            "follow_total": 0,
            "collab_total": 0,
            "quality_total": 0,
            "overall_total": 0.0,
        }
        for user_id, user in team_map.items()
    }

    for rating in ratings:
        if rating.rated_user_id not in summary_map:
            continue
        bucket = summary_map[rating.rated_user_id]
        bucket["count"] += 1
        bucket["follow_total"] += rating.follow_through
        bucket["collab_total"] += rating.collaboration
        bucket["quality_total"] += rating.quality
        bucket["overall_total"] += (rating.follow_through + rating.collaboration + rating.quality) / 3.0

    summary_rows = []
    for bucket in summary_map.values():
        count = bucket["count"]
        summary_rows.append(
            {
                "user": bucket["user"],
                "rating_count": count,
                "avg_follow_through": round(bucket["follow_total"] / count, 2) if count else None,
                "avg_collaboration": round(bucket["collab_total"] / count, 2) if count else None,
                "avg_quality": round(bucket["quality_total"] / count, 2) if count else None,
                "avg_overall": round(bucket["overall_total"] / count, 2) if count else None,
            }
        )

    summary_rows.sort(
        key=lambda row: (
            row["avg_overall"] is None,
            -(row["avg_overall"] or 0),
            row["user"].full_name.lower(),
        )
    )

    expected_targets = [user for user in team_map.values() if user.id != current_user.id]
    rated_by_current = {
        rating.rated_user_id
        for rating in ratings
        if rating.rater_user_id == current_user.id
    }
    pending_targets = [user for user in expected_targets if user.id not in rated_by_current]

    return render_template(
        "projects/ratings_overview.html",
        project=project,
        summary_rows=summary_rows,
        ratings=ratings,
        pending_targets=pending_targets,
        expected_targets=expected_targets,
    )
