from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required

from app.models import ActionTemplate, Project
from app.services.geo_matcher import get_nearby_projects
from app.services.file_handler import (
    FileHandlerError,
    decode_local_download_token,
    get_local_file_absolute_path,
)
from app.utils import strip_html


main_bp = Blueprint("main", __name__)


BLOG_POSTS = [
    {
        "slug": "why-small-civic-teams-win",
        "title": "Why Small Civic Teams Win",
        "excerpt": "Focused teams with clear milestones often outperform large, unstructured volunteer groups.",
        "content": "<p>Small teams can execute faster when roles are explicit and accountability is clear.</p>",
    },
    {
        "slug": "from-intent-to-impact",
        "title": "From Intent to Impact",
        "excerpt": "Turning civic concern into outcomes requires measurable definitions of success.",
        "content": "<p>Impact starts by defining outcomes, owners, and delivery cadence from day one.</p>",
    },
    {
        "slug": "templates-scale-community-action",
        "title": "How Templates Scale Community Action",
        "excerpt": "Reusable action templates preserve what worked and accelerate future projects.",
        "content": "<p>When communities replicate proven structures, they reduce setup time and risk.</p>",
    },
]


@main_bp.get("/")
def index():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if lat is not None and lon is not None:
        nearby_projects = get_nearby_projects(lat, lon, max_km=50)[:3]
        widget_title = "Active near you"
    else:
        nearby_projects = (
            Project.query.filter_by(is_published=True)
            .filter(Project.status.in_(["assembling", "active"]))
            .order_by(Project.created_at.desc())
            .limit(3)
            .all()
        )
        widget_title = "Active right now"

    completed_projects = (
        Project.query.filter_by(status="completed", is_published=True)
        .order_by(Project.updated_at.desc())
        .limit(3)
        .all()
    )
    templates = ActionTemplate.query.filter_by(is_published=True).order_by(ActionTemplate.updated_at.desc()).limit(3).all()

    return render_template(
        "main/index.html",
        nearby_projects=nearby_projects,
        widget_title=widget_title,
        completed_projects=completed_projects,
        templates=templates,
    )


@main_bp.get("/how-it-works")
def how_it_works():
    return render_template("main/how_it_works.html")


@main_bp.get("/for-organizations")
def for_organizations():
    return render_template("main/for_organizations.html")


@main_bp.get("/pricing")
def pricing():
    return render_template("main/pricing.html")


@main_bp.get("/about")
def about():
    return render_template("main/about.html")


@main_bp.get("/blog")
def blog_index():
    return render_template("main/blog_index.html", posts=BLOG_POSTS)


@main_bp.get("/blog/<slug>")
def blog_post(slug):
    post = next((post for post in BLOG_POSTS if post["slug"] == slug), None)
    if not post:
        return render_template("errors/404.html"), 404
    return render_template("main/blog_post.html", post=post)


@main_bp.get("/contact")
def contact_get():
    return render_template("main/contact.html")


@main_bp.post("/contact")
def contact_post():
    name = strip_html(request.form.get("name", ""), 120)
    email = strip_html(request.form.get("email", ""), 255)
    message = strip_html(request.form.get("message", ""), 1500)

    if not name or not email or not message:
        flash("Please complete all fields.", "danger")
        return redirect(url_for("main.contact_get"))

    flash("Message sent! We'll get back to you within 2 business days.", "success")
    return redirect(url_for("main.contact_get"))


@main_bp.get("/privacy")
def privacy():
    return render_template("main/privacy.html")


@main_bp.get("/terms")
def terms():
    return render_template("main/terms.html")


@main_bp.get("/files/local/<token>")
@login_required
def local_file_download(token):
    try:
        storage_path = decode_local_download_token(token, max_age=3600)
        absolute_file = get_local_file_absolute_path(storage_path)
    except FileHandlerError:
        abort(404)

    if not absolute_file.exists() or not absolute_file.is_file():
        abort(404)

    return send_file(absolute_file, as_attachment=True, download_name=absolute_file.name)
