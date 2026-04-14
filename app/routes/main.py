import mimetypes
from datetime import timezone

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import cast, or_

from app.extensions import db
from app.models import ActionTemplate, Project
from app.services.geo_matcher import get_nearby_projects
from app.services.file_handler import (
    FileHandlerError,
    decode_local_download_token,
    get_local_file_absolute_path,
)
from app.utils import strip_html, utcnow


main_bp = Blueprint("main", __name__)

from app.models import BLOG_CATEGORIES, BlogPost


BLOG_CATEGORY_LABELS = {
    "civic_action": "Civic Action",
    "platform_updates": "Platform Updates",
    "success_stories": "Success Stories",
    "guides_and_tips": "Guides and Tips",
    "organizations": "Organizations",
    "announcements": "Announcements",
}


def _preview_serializer() -> URLSafeTimedSerializer:
    from flask import current_app

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _valid_preview_token(post_id: int, token: str, max_age_seconds: int = 86400) -> bool:
    if not token:
        return False
    try:
        payload = _preview_serializer().loads(token, salt="blog-preview", max_age=max_age_seconds)
    except BadSignature:
        return False
    return int(payload.get("post_id", -1)) == int(post_id)


def _coerce_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _published_blog_query():
    now = utcnow()
    return BlogPost.query.filter(
        BlogPost.deleted_at.is_(None),
        BlogPost.status == "published",
        or_(BlogPost.published_at.is_(None), BlogPost.published_at <= now),
    )


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
    q = strip_html(request.args.get("q", ""), 120).strip()
    category = strip_html(request.args.get("category", ""), 100).strip().lower()
    tag = strip_html(request.args.get("tag", ""), 40).strip().lower()

    query = _published_blog_query().order_by(
        BlogPost.is_pinned.desc(),
        BlogPost.is_featured.desc(),
        BlogPost.published_at.desc(),
        BlogPost.created_at.desc(),
    )

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                BlogPost.title.ilike(like_q),
                BlogPost.summary.ilike(like_q),
                cast(BlogPost.tags, db.String).ilike(like_q),
            )
        )

    if category in BLOG_CATEGORIES:
        query = query.filter(BlogPost.category == category)

    if tag:
        query = query.filter(cast(BlogPost.tags, db.String).ilike(f'%"{tag}"%'))

    page = max(1, request.args.get("page", 1, type=int))
    pagination = query.paginate(page=page, per_page=12, error_out=False)

    featured_posts = (
        _published_blog_query()
        .filter(BlogPost.is_featured.is_(True))
        .order_by(BlogPost.is_pinned.desc(), BlogPost.published_at.desc())
        .limit(3)
        .all()
    )

    return render_template(
        "main/blog_index.html",
        pagination=pagination,
        featured_posts=featured_posts,
        q=q,
        category=category,
        tag=tag,
        category_labels=BLOG_CATEGORY_LABELS,
    )


@main_bp.get("/blog/<slug>")
def blog_post(slug):
    post = BlogPost.query.filter(BlogPost.deleted_at.is_(None), BlogPost.slug == slug).first()
    if not post:
        return render_template("errors/404.html"), 404

    preview_token = (request.args.get("preview_token") or "").strip()
    preview_mode = _valid_preview_token(post.id, preview_token)

    published_at_utc = _coerce_utc(post.published_at)
    is_publicly_visible = (
        post.status == "published"
        and (published_at_utc is None or published_at_utc <= utcnow())
    )

    if not preview_mode and not is_publicly_visible:
        return render_template("errors/404.html"), 404

    related_posts = (
        _published_blog_query()
        .filter(BlogPost.id != post.id)
        .filter(BlogPost.category == post.category)
        .order_by(BlogPost.published_at.desc())
        .limit(3)
        .all()
    )

    return render_template("main/blog_post.html", post=post, related_posts=related_posts, preview_mode=preview_mode)


@main_bp.post("/blog/<slug>/track-view")
def blog_track_view(slug):
    post = _published_blog_query().filter(BlogPost.slug == slug).first()
    if not post:
        return jsonify({"success": False}), 404

    post.views_count = int(post.views_count or 0) + 1
    db.session.commit()
    return jsonify({"success": True, "views_count": post.views_count})


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

    mime_type, _encoding = mimetypes.guess_type(absolute_file.name)
    is_image = bool(mime_type and mime_type.startswith("image/"))

    return send_file(
        absolute_file,
        mimetype=mime_type,
        as_attachment=not is_image,
        download_name=absolute_file.name,
    )
