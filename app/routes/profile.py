from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.profile_forms import EditProfileForm
from app.models import PeerRating, Project, ProjectRole, Skill, User
from app.services.file_handler import FileHandlerError, upload_file_to_s3
from app.services.reputation_engine import update_badge_counts
from app.utils import strip_html


profile_bp = Blueprint("profile", __name__)


@profile_bp.get("/profile/<username>")
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    completed_roles = (
        ProjectRole.query.join(Project, Project.id == ProjectRole.project_id)
        .filter(ProjectRole.filled_by_user_id == user.id, Project.status == "completed")
        .all()
    )

    track_record = []
    for role in completed_roles:
        ratings = PeerRating.query.filter_by(project_id=role.project_id, rated_user_id=user.id).all()
        avg_rating = None
        if ratings:
            avg_rating = round(
                sum((rating.follow_through + rating.collaboration + rating.quality) / 3 for rating in ratings)
                / len(ratings),
                2,
            )

        track_record.append(
            {
                "project": role.project,
                "role": role,
                "avg_rating": avg_rating,
                "testimonial": next((rating.testimonial for rating in ratings if rating.testimonial), ""),
            }
        )

    badges = update_badge_counts(user.id)

    reputation_visible = (user.rating_count or 0) >= 3 and user.reputation_score is not None

    return render_template(
        "profile/public.html",
        user_profile=user,
        track_record=track_record,
        badges=badges,
        reputation_visible=reputation_visible,
    )


@profile_bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    form = EditProfileForm(obj=current_user)
    form.skills.choices = [(skill.id, skill.name) for skill in Skill.query.filter_by(is_active=True).order_by(Skill.name).all()]

    if form.validate_on_submit():
        current_user.bio = strip_html(form.bio.data or "", 2000)
        current_user.city = strip_html(form.city.data or "", 200)
        current_user.country = strip_html(form.country.data or "", 100)
        current_user.availability_hours = form.availability_hours.data
        current_user.is_open_to_projects = form.is_open_to_projects.data
        current_user.domain_interests = form.domain_interests.data or []
        current_user.skills = Skill.query.filter(Skill.id.in_(form.skills.data or [])).all()

        if form.profile_photo.data:
            try:
                storage_path = upload_file_to_s3(form.profile_photo.data, f"avatar_{current_user.id}", {"image/jpeg", "image/png", "image/gif"})
                current_user.profile_photo_url = storage_path
            except FileHandlerError as exc:
                flash(str(exc), "danger")
                return render_template("profile/edit.html", form=form)

        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile.public_profile", username=current_user.username))

    if not form.is_submitted():
        form.skills.data = [skill.id for skill in current_user.skills]
        form.domain_interests.data = current_user.domain_interests or []

    return render_template("profile/edit.html", form=form)
