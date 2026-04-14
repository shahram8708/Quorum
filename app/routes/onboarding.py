from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.profile_forms import OnboardingForm
from app.models import Skill


onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


@onboarding_bp.route("", methods=["GET", "POST"])
@login_required
def index():
    form = OnboardingForm()
    form.skills.choices = [(skill.id, skill.name) for skill in Skill.query.filter_by(is_active=True).order_by(Skill.name).all()]

    if form.validate_on_submit():
        current_user.city = (form.city.data or "").strip()
        current_user.country = (form.country.data or "").strip()
        current_user.availability_hours = form.availability_hours.data
        current_user.is_open_to_projects = form.is_open_to_projects.data
        current_user.domain_interests = form.domain_interests.data or []
        selected_skill_ids = form.skills.data or []
        current_user.skills = Skill.query.filter(Skill.id.in_(selected_skill_ids)).all() if selected_skill_ids else []
        current_user.onboarding_complete = current_user.has_onboarding_inputs()

        if current_user.needs_onboarding:
            flash("Please complete all onboarding fields before continuing.", "danger")
            return render_template("onboarding/index.html", form=form)

        db.session.commit()
        flash("Profile set up! Here are projects matching your skills.", "success")
        return redirect(url_for("dashboard.home"))

    if form.is_submitted():
        flash("Please complete all onboarding fields before continuing.", "danger")

    if not form.is_submitted():
        form.city.data = current_user.city
        form.country.data = current_user.country
        form.availability_hours.data = current_user.availability_hours
        form.is_open_to_projects.data = current_user.is_open_to_projects
        form.domain_interests.data = current_user.domain_interests or []
        form.skills.data = [skill.id for skill in current_user.skills]

    return render_template(
        "onboarding/index.html",
        form=form,
        minimal_nav_mode=True,
        minimal_nav_label="Log Out",
        minimal_nav_link=url_for("auth.logout"),
    )
