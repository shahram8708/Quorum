from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.profile_forms import EditProfileForm
from app.models import PeerRating, Skill, User
from app.services.file_handler import FileHandlerError, delete_file_from_s3, upload_file_to_s3
from app.services.reputation_engine import get_completed_projects_for_user, update_badge_counts
from app.utils import strip_html


profile_bp = Blueprint("profile", __name__)


@profile_bp.get("/profile/<username>")
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    completed_projects = get_completed_projects_for_user(user.id)

    track_record = []
    for project in completed_projects:
        user_role_titles = [role.title for role in project.roles if role.filled_by_user_id == user.id]
        if project.creator_user_id == user.id and user_role_titles:
            role_label = f"Project Creator, {', '.join(user_role_titles)}"
        elif project.creator_user_id == user.id:
            role_label = "Project Creator"
        elif user_role_titles:
            role_label = ", ".join(user_role_titles)
        else:
            role_label = "Contributor"

        ratings = PeerRating.query.filter_by(project_id=project.id, rated_user_id=user.id).all()
        avg_rating = None
        if ratings:
            avg_rating = round(
                sum((rating.follow_through + rating.collaboration + rating.quality) / 3 for rating in ratings)
                / len(ratings),
                2,
            )

        track_record.append(
            {
                "project": project,
                "role_label": role_label,
                "avg_rating": avg_rating,
                "testimonial": next((rating.testimonial for rating in ratings if rating.testimonial), ""),
            }
        )

    badges = update_badge_counts(user.id)
    completed_domain_count = len({(project.domain or "").strip() for project in completed_projects if (project.domain or "").strip()})

    reputation_visible = (user.rating_count or 0) >= 3 and user.reputation_score is not None

    return render_template(
        "profile/public.html",
        user_profile=user,
        track_record=track_record,
        badges=badges,
        completed_domain_count=completed_domain_count,
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

        uploaded_photo = form.profile_photo.data
        if uploaded_photo and getattr(uploaded_photo, "filename", ""):
            try:
                previous_photo_path = current_user.profile_photo_url
                storage_path = upload_file_to_s3(
                    uploaded_photo,
                    f"avatar_{current_user.id}",
                    {"image/jpeg", "image/png", "image/gif", "image/webp"},
                )
                current_user.profile_photo_url = storage_path

                if previous_photo_path and previous_photo_path != storage_path:
                    try:
                        delete_file_from_s3(previous_photo_path)
                    except FileHandlerError:
                        # Do not fail profile updates due to best-effort cleanup.
                        pass
            except FileHandlerError as exc:
                flash(str(exc), "danger")
                return render_template("profile/edit.html", form=form)

        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile.public_profile", username=current_user.username))

    if form.is_submitted() and form.errors:
        for field_name, errors in form.errors.items():
            field = getattr(form, field_name, None)
            field_label = field.label.text if field is not None else field_name
            for error in errors:
                flash(f"{field_label}: {error}", "danger")

    if not form.is_submitted():
        form.skills.data = [skill.id for skill in current_user.skills]
        form.domain_interests.data = current_user.domain_interests or []

    return render_template("profile/edit.html", form=form)
