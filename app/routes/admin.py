import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import and_, cast, func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (
    ActionTemplate,
    AIUsageLog,
    BLOG_CATEGORIES,
    BLOG_STATUSES,
    BlogPost,
    CivicChallenge,
    Notification,
    OrganizationAccount,
    PeerRating,
    Project,
    ProjectOutcome,
    ProjectRole,
    RazorpayPayment,
    RoleApplication,
    Skill,
    Task,
    User,
)
from app.routes import admin_required, create_notification, validate_ajax_csrf
from app.services.email_service import send_outcome_approved
from app.services.file_handler import (
    FileHandlerError,
    delete_file_from_s3,
    generate_presigned_url,
    upload_file_to_s3,
)
from app.services.template_generator import can_generate_template, convert_to_template
from app.utils import (
    estimate_reading_time_minutes,
    normalize_tags,
    sanitize_rich_html,
    slugify_text,
    strip_html,
    utcnow,
)


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger("quorum.admin_actions")

BLOG_PAGE_SIZE = 15
ANALYTICS_RANGES = {"7d", "30d", "90d", "12m", "all"}

BLOG_CATEGORY_LABELS = {
    "civic_action": "Civic Action",
    "platform_updates": "Platform Updates",
    "success_stories": "Success Stories",
    "guides_and_tips": "Guides and Tips",
    "organizations": "Organizations",
    "announcements": "Announcements",
}

BLOG_STATUS_LABELS = {
    "draft": "Draft",
    "published": "Published",
    "archived": "Archived",
}

PROJECT_STATUS_LABELS = {
    "draft": "Draft",
    "assembling": "Assembling",
    "launch_ready": "Launch Ready",
    "active": "Active",
    "completed": "Completed",
    "archived": "Archived",
}

AI_FEATURE_LABELS = {
    "description_enhancer": "Description Enhancer",
    "scope_validator": "Scope Validator",
    "role_suggester": "Role Suggester",
    "recommendations": "Recommendations",
    "template_search": "Template Search",
    "civic_pulse": "Civic Pulse",
    "outcome_assistant": "Outcome Assistant",
    "challenge_discovery": "Challenge Discovery",
}

SUBSCRIPTION_PLAN_LABELS = {
    "creator_pro": "Creator Pro",
    "org_starter": "Org Starter",
    "org_team": "Org Team",
}

AI_FEATURE_KEY_ALIASES = {
    "enhance_project_description": "description_enhancer",
    "validate_project_scope": "scope_validator",
    "suggest_project_roles": "role_suggester",
    "personalized_recommendations": "recommendations",
    "ai_template_search": "template_search",
    "fetch_civic_pulse": "civic_pulse",
    "generate_outcome_draft": "outcome_assistant",
    "discover_civic_challenges": "challenge_discovery",
}

SUBSCRIPTION_PLAN_ALIASES = {
    "creator": "creator_pro",
    "creatorpro": "creator_pro",
    "creator_plus": "creator_pro",
    "organization_starter": "org_starter",
    "orgstarter": "org_starter",
    "org_start": "org_starter",
    "organization_team": "org_team",
    "orgteam": "org_team",
}


def _normalize_lookup_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_ai_feature_key(raw_name: str | None):
    key = _normalize_lookup_key(raw_name)
    if not key:
        return None
    if key in AI_FEATURE_LABELS:
        return key
    return AI_FEATURE_KEY_ALIASES.get(key)


def _normalize_plan_key(raw_name: str | None):
    key = _normalize_lookup_key(raw_name)
    if not key:
        return None
    if key in SUBSCRIPTION_PLAN_LABELS:
        return key
    alias = SUBSCRIPTION_PLAN_ALIASES.get(key)
    if alias:
        return alias
    if key.startswith("creator"):
        return "creator_pro"
    if ("org" in key or "organization" in key) and "starter" in key:
        return "org_starter"
    if ("org" in key or "organization" in key) and "team" in key:
        return "org_team"
    return None


def _preview_serializer() -> URLSafeTimedSerializer:
    from flask import current_app

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _generate_blog_preview_token(post_id: int) -> str:
    return _preview_serializer().dumps({"post_id": int(post_id)}, salt="blog-preview")


def _is_valid_blog_preview_token(post_id: int, token: str, max_age_seconds: int = 86400) -> bool:
    if not token:
        return False
    try:
        payload = _preview_serializer().loads(token, salt="blog-preview", max_age=max_age_seconds)
    except BadSignature:
        return False
    return int(payload.get("post_id", -1)) == int(post_id)


def _paginate(query, per_page=20):
    page = max(1, request.args.get("page", 1, type=int))
    return query.paginate(page=page, per_page=per_page, error_out=False)


def _wants_json_response() -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    return bool(
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.args.get("format") == "json"
        or "application/json" in accept
    )


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_utc_datetime(value: str | None):
    raw = strip_html(value or "", 64).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_utc(dt_value):
    if dt_value is None:
        return None
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)


def _log_admin_action(action: str, details: dict | None = None):
    admin_id = getattr(current_user, "id", None)
    logger.info(
        "admin_action action=%s admin_id=%s details=%s",
        action,
        admin_id,
        details or {},
    )


def _generate_unique_blog_slug(source: str, exclude_post_id: int | None = None) -> str:
    base_slug = slugify_text(source or "post", max_len=160)
    candidate = base_slug
    suffix = 2
    while True:
        query = BlogPost.query.filter(BlogPost.slug == candidate)
        if exclude_post_id:
            query = query.filter(BlogPost.id != exclude_post_id)
        if query.first() is None:
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


def _public_blog_query_base():
    now = utcnow()
    return BlogPost.query.filter(
        BlogPost.deleted_at.is_(None),
        BlogPost.status == "published",
        or_(BlogPost.published_at.is_(None), BlogPost.published_at <= now),
    )


def _build_period_config(range_key: str):
    now = utcnow()
    key = (range_key or "30d").strip().lower()
    if key not in ANALYTICS_RANGES:
        key = "30d"

    if key == "all":
        earliest = db.session.query(func.min(User.created_at)).scalar() or now
        start = _as_utc(earliest) or now
        previous_start = None
        previous_end = None
        bucket_mode = "month"
    elif key == "12m":
        start = now - timedelta(days=365)
        previous_end = start
        previous_start = start - timedelta(days=365)
        bucket_mode = "month"
    else:
        days = int(key.replace("d", ""))
        start = now - timedelta(days=days)
        previous_end = start
        previous_start = start - timedelta(days=days)
        bucket_mode = "day"

    return {
        "key": key,
        "start": start,
        "end": now,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "bucket_mode": bucket_mode,
    }


def _bucket_key(dt_value, bucket_mode: str):
    dt_value = _as_utc(dt_value)
    if not dt_value:
        return None
    if bucket_mode == "month":
        return dt_value.strftime("%Y-%m")
    return dt_value.strftime("%Y-%m-%d")


def _build_bucket_labels(start_dt, end_dt, bucket_mode: str):
    start_dt = _as_utc(start_dt)
    end_dt = _as_utc(end_dt)
    labels = []
    keys = []

    cursor = start_dt
    if bucket_mode == "month":
        cursor = datetime(start_dt.year, start_dt.month, 1, tzinfo=timezone.utc)
        while cursor <= end_dt:
            keys.append(cursor.strftime("%Y-%m"))
            labels.append(cursor.strftime("%b %Y"))
            if cursor.month == 12:
                cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
    else:
        cursor = datetime(start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc)
        while cursor <= end_dt:
            keys.append(cursor.strftime("%Y-%m-%d"))
            labels.append(cursor.strftime("%d %b"))
            cursor = cursor + timedelta(days=1)

    return keys, labels


def _pct_change(current_value: float, previous_value: float | None):
    if previous_value in {None, 0}:
        if current_value == 0:
            return 0.0
        return None
    return round(((current_value - previous_value) / previous_value) * 100.0, 2)


@admin_bp.get("")
@login_required
@admin_required
def dashboard():
    stats = {
        "total_users": User.query.count(),
        "active_projects": Project.query.filter(Project.status.in_(["assembling", "active", "launch_ready"])).count(),
        "completed_projects": Project.query.filter_by(status="completed").count(),
        "pending_outcomes": ProjectOutcome.query.filter_by(is_published=False).count(),
        "flagged_projects": Project.query.filter_by(is_flagged=True).count(),
        "total_templates": ActionTemplate.query.count(),
        "organizations": OrganizationAccount.query.count(),
    }
    recent_activity = Notification.query.order_by(Notification.created_at.desc()).limit(10).all()
    return render_template("admin/dashboard.html", stats=stats, recent_activity=recent_activity)


@admin_bp.get("/projects")
@login_required
@admin_required
def projects():
    reason_filter = request.args.get("reason", "").strip()
    status_filter = request.args.get("status", "").strip().lower()

    if status_filter:
        query = Project.query.filter(Project.status == status_filter)
    else:
        query = Project.query.filter_by(is_flagged=True)

    if reason_filter:
        query = query.filter(Project.flag_reason.ilike(f"%{reason_filter}%"))

    pagination = _paginate(query.order_by(Project.updated_at.desc()))
    return render_template(
        "admin/projects.html",
        pagination=pagination,
        reason_filter=reason_filter,
        status_filter=status_filter,
    )


@admin_bp.post("/projects/<int:id>/unflag")
@login_required
@admin_required
def unflag_project(id):
    project = Project.query.get_or_404(id)
    project.is_flagged = False
    project.flag_reason = None
    db.session.commit()
    flash("Project unflagged.", "success")
    return redirect(url_for("admin.projects"))


@admin_bp.post("/projects/<int:id>/archive")
@login_required
@admin_required
def archive_project(id):
    project = Project.query.get_or_404(id)
    project.status = "archived"
    db.session.commit()
    flash("Project archived.", "success")
    return redirect(url_for("admin.projects"))


@admin_bp.post("/projects/<int:id>/warn")
@login_required
@admin_required
def warn_project_creator(id):
    project = Project.query.get_or_404(id)
    message = strip_html(request.form.get("message", "Please review your project content."), 1000)

    create_notification(
        project.creator_user_id,
        "moderation_warning",
        f"Moderation warning: {project.title}",
        message,
        f"/my-projects/{project.id}/manage",
    )
    db.session.commit()

    flash("Warning email sent.", "success")
    return redirect(url_for("admin.projects"))


@admin_bp.get("/outcomes")
@login_required
@admin_required
def outcomes():
    query = ProjectOutcome.query.filter_by(is_published=False).order_by(ProjectOutcome.submitted_at.desc())
    pagination = _paginate(query)
    return render_template("admin/outcomes.html", pagination=pagination)


@admin_bp.get("/outcomes/<int:id>")
@login_required
@admin_required
def outcome_detail(id):
    outcome = ProjectOutcome.query.get_or_404(id)
    return render_template("admin/outcome_detail.html", outcome=outcome)


@admin_bp.post("/outcomes/<int:id>/approve")
@login_required
@admin_required
def approve_outcome(id):
    outcome = ProjectOutcome.query.get_or_404(id)
    rating = strip_html(request.form.get("outcome_rating", "partial_success"), 50)
    if rating not in {"full_success", "partial_success", "not_achieved"}:
        rating = "partial_success"

    outcome.is_published = True
    outcome.outcome_rating = rating
    db.session.commit()

    project = outcome.project

    if can_generate_template(project.id):
        has_template = ActionTemplate.query.filter_by(source_project_id=project.id).first()
        if not has_template:
            convert_to_template(project.id)

    create_notification(
        project.creator_user_id,
        "outcome_approved",
        f"Outcome approved for {project.title}",
        "Your outcome report is now published.",
        f"/projects/{project.id}",
    )
    db.session.commit()

    try:
        send_outcome_approved(project.creator, project)
    except Exception:
        pass

    flash("Outcome approved and published.", "success")
    return redirect(url_for("admin.outcomes"))


@admin_bp.post("/outcomes/<int:id>/reject")
@login_required
@admin_required
def reject_outcome(id):
    outcome = ProjectOutcome.query.get_or_404(id)
    reason = strip_html(request.form.get("reason", "Please revise and resubmit."), 1000)

    create_notification(
        outcome.project.creator_user_id,
        "outcome_rejected",
        f"Outcome report needs revision: {outcome.project.title}",
        reason,
        f"/my-projects/{outcome.project.id}/outcome",
    )

    db.session.delete(outcome)
    db.session.commit()
    flash("Outcome rejected. Creator notified.", "info")
    return redirect(url_for("admin.outcomes"))


@admin_bp.get("/blog")
@login_required
@admin_required
def blog():
    q = strip_html(request.args.get("q", ""), 200).strip()
    category_filter = strip_html(request.args.get("category", ""), 100).strip().lower()
    status_filter = strip_html(request.args.get("status", ""), 50).strip().lower()
    sort_key = strip_html(request.args.get("sort", "newest"), 40).strip().lower()

    query = BlogPost.query.options(joinedload(BlogPost.author)).filter(BlogPost.deleted_at.is_(None))
    if q:
        like_q = f"%{q}%"
        query = query.filter(
            or_(
                BlogPost.title.ilike(like_q),
                BlogPost.slug.ilike(like_q),
                cast(BlogPost.tags, db.String).ilike(like_q),
            )
        )
    if category_filter in BLOG_CATEGORIES:
        query = query.filter(BlogPost.category == category_filter)
    if status_filter in BLOG_STATUSES:
        query = query.filter(BlogPost.status == status_filter)

    if sort_key == "most_viewed":
        query = query.order_by(BlogPost.views_count.desc(), BlogPost.created_at.desc())
    elif sort_key == "recently_updated":
        query = query.order_by(BlogPost.updated_at.desc())
    else:
        sort_key = "newest"
        query = query.order_by(BlogPost.created_at.desc())

    pagination = _paginate(query, per_page=BLOG_PAGE_SIZE)

    status_rows = (
        db.session.query(BlogPost.status, func.count(BlogPost.id))
        .filter(BlogPost.deleted_at.is_(None))
        .group_by(BlogPost.status)
        .all()
    )
    status_counts = {key: count for key, count in status_rows}

    return render_template(
        "admin/blog.html",
        pagination=pagination,
        q=q,
        category_filter=category_filter,
        status_filter=status_filter,
        sort_key=sort_key,
        category_labels=BLOG_CATEGORY_LABELS,
        status_labels=BLOG_STATUS_LABELS,
        status_counts=status_counts,
    )


@admin_bp.get("/blog/new")
@login_required
@admin_required
def blog_new():
    now = utcnow()
    return render_template(
        "admin/blog_editor.html",
        post=None,
        category_labels=BLOG_CATEGORY_LABELS,
        status_labels=BLOG_STATUS_LABELS,
        default_published_at=now.strftime("%Y-%m-%dT%H:%M"),
        preview_url=None,
        last_saved_seconds=None,
    )


@admin_bp.get("/blog/<int:id>/edit")
@login_required
@admin_required
def blog_edit(id):
    post = BlogPost.query.options(joinedload(BlogPost.author)).filter(BlogPost.deleted_at.is_(None), BlogPost.id == id).first_or_404()
    last_saved_seconds = None
    if post.updated_at:
        updated_at = post.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        else:
            updated_at = updated_at.astimezone(timezone.utc)
        last_saved_seconds = max(0, int((utcnow() - updated_at).total_seconds()))

    return render_template(
        "admin/blog_editor.html",
        post=post,
        category_labels=BLOG_CATEGORY_LABELS,
        status_labels=BLOG_STATUS_LABELS,
        default_published_at=(post.published_at or utcnow()).strftime("%Y-%m-%dT%H:%M"),
        preview_url=url_for("admin.blog_preview", id=post.id),
        last_saved_seconds=last_saved_seconds,
    )


@admin_bp.post("/blog/save")
@login_required
@admin_required
def blog_save():
    if request.is_json:
        try:
            validate_ajax_csrf()
        except ValidationError:
            return jsonify({"success": False, "error": "Invalid CSRF token."}), 400
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form

    post_id_raw = payload.get("post_id")
    autosave = _truthy(payload.get("autosave"))
    submit_action = strip_html(payload.get("submit_action", ""), 50).strip().lower()

    post = None
    if str(post_id_raw or "").strip().isdigit():
        post = BlogPost.query.filter(BlogPost.deleted_at.is_(None), BlogPost.id == int(post_id_raw)).first()

    is_create = post is None
    if is_create:
        post = BlogPost(author_user_id=current_user.id, title="", slug="")
        db.session.add(post)

    previous_status = post.status

    title = strip_html(payload.get("title", post.title or ""), 500).strip()
    slug_input = strip_html(payload.get("slug", post.slug or ""), 600).strip()
    content_html = sanitize_rich_html(payload.get("content", post.content or ""))
    category = strip_html(payload.get("category", post.category or "civic_action"), 100).strip().lower()
    status = strip_html(payload.get("status", post.status or "draft"), 50).strip().lower()
    summary = strip_html(payload.get("summary", post.summary or ""), 300)
    cover_image_url = strip_html(payload.get("cover_image_url", post.cover_image_url or ""), 500).strip()
    cover_image_alt = strip_html(payload.get("cover_image_alt", post.cover_image_alt or ""), 300)
    meta_title = strip_html(payload.get("meta_title", post.meta_title or ""), 200)
    meta_description = strip_html(payload.get("meta_description", post.meta_description or ""), 300)

    if submit_action == "publish_now":
        status = "published"
    elif submit_action in {"save_draft", "unpublish"}:
        status = "draft"

    if category not in BLOG_CATEGORIES:
        category = "civic_action"
    if status not in BLOG_STATUSES:
        status = "draft"

    tags = normalize_tags(payload.get("tags", post.tags or []), max_tags=10)

    upload_file = request.files.get("cover_image_file")
    if upload_file and upload_file.filename:
        try:
            raw_data = upload_file.read()
            upload_file.seek(0)
            if len(raw_data) > 5 * 1024 * 1024:
                raise FileHandlerError("Cover image must be under 5MB.")

            new_storage_path = upload_file_to_s3(
                upload_file,
                upload_file.filename,
                allowed_types={"image/jpeg", "image/png", "image/webp"},
            )
            old_storage_path = post.cover_image_url
            cover_image_url = new_storage_path
            if old_storage_path and old_storage_path != new_storage_path:
                try:
                    delete_file_from_s3(old_storage_path)
                except Exception:
                    pass
        except FileHandlerError as error:
            db.session.rollback()
            if _wants_json_response():
                return jsonify({"success": False, "error": str(error)}), 400
            flash(str(error), "danger")
            if post.id:
                return redirect(url_for("admin.blog_edit", id=post.id))
            return redirect(url_for("admin.blog_new"))

    if not summary and content_html:
        summary = strip_html(content_html, 300)

    if not title and not autosave:
        if _wants_json_response():
            return jsonify({"success": False, "error": "Title is required."}), 400
        flash("Title is required.", "danger")
        if post.id:
            return redirect(url_for("admin.blog_edit", id=post.id))
        return redirect(url_for("admin.blog_new"))

    if status == "published" and not content_html and not autosave:
        if _wants_json_response():
            return jsonify({"success": False, "error": "Published posts require content."}), 400
        flash("Published posts require content.", "danger")
        if post.id:
            return redirect(url_for("admin.blog_edit", id=post.id))
        return redirect(url_for("admin.blog_new"))

    post.title = title or post.title or "Untitled Post"
    post.slug = _generate_unique_blog_slug(slug_input or post.title, exclude_post_id=post.id)
    post.category = category
    post.tags = tags
    post.summary = summary
    post.content = content_html
    post.reading_time_minutes = estimate_reading_time_minutes(content_html)
    post.status = status
    post.is_featured = _truthy(payload.get("is_featured", post.is_featured))
    post.is_pinned = _truthy(payload.get("is_pinned", post.is_pinned))
    post.meta_title = meta_title or None
    post.meta_description = meta_description or None
    post.cover_image_url = cover_image_url or None
    post.cover_image_alt = cover_image_alt or None
    if is_create:
        post.views_count = 0

    selected_publish_dt = _parse_utc_datetime(payload.get("published_at"))
    if post.status == "published":
        if previous_status != "published":
            post.published_at = selected_publish_dt or utcnow()
        elif selected_publish_dt:
            post.published_at = selected_publish_dt
        elif not post.published_at:
            post.published_at = utcnow()
    elif submit_action == "unpublish":
        post.published_at = None

    db.session.commit()
    _log_admin_action(
        "blog_save",
        {
            "post_id": post.id,
            "slug": post.slug,
            "status": post.status,
            "autosave": autosave,
            "is_create": is_create,
        },
    )

    redirect_url = url_for("admin.blog_edit", id=post.id)
    if _wants_json_response() or autosave:
        return jsonify(
            {
                "success": True,
                "post_id": post.id,
                "slug": post.slug,
                "redirect_url": redirect_url,
                "reading_time_minutes": post.reading_time_minutes,
                "saved_at": utcnow().isoformat(),
            }
        )

    if post.status == "published":
        flash("Post published successfully.", "success")
    elif autosave:
        flash("Draft autosaved.", "info")
    else:
        flash("Draft saved.", "success")
    return redirect(redirect_url)


@admin_bp.post("/blog/<int:id>/delete")
@login_required
@admin_required
def blog_delete(id):
    post = BlogPost.query.get_or_404(id)
    hard_delete = _truthy(request.form.get("hard_delete") or (request.get_json(silent=True) or {}).get("hard_delete"))

    if hard_delete:
        storage_path = post.cover_image_url
        db.session.delete(post)
        db.session.commit()
        if storage_path:
            try:
                delete_file_from_s3(storage_path)
            except Exception:
                pass
        _log_admin_action("blog_hard_delete", {"post_id": id})
        flash("Post permanently deleted.", "success")
    else:
        post.deleted_at = utcnow()
        db.session.commit()
        _log_admin_action("blog_soft_delete", {"post_id": id})
        flash("Post moved to trash.", "info")

    if _wants_json_response():
        return jsonify({"success": True})
    return redirect(url_for("admin.blog"))


@admin_bp.post("/blog/<int:id>/duplicate")
@login_required
@admin_required
def blog_duplicate(id):
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 400

    original = BlogPost.query.get_or_404(id)
    copy_title = f"Copy of {original.title}"[:500]

    duplicated = BlogPost(
        title=copy_title,
        slug=_generate_unique_blog_slug(copy_title),
        author_user_id=current_user.id,
        category=original.category,
        tags=list(original.tags or []),
        cover_image_url=original.cover_image_url,
        cover_image_alt=original.cover_image_alt,
        summary=original.summary,
        content=original.content,
        reading_time_minutes=original.reading_time_minutes,
        status="draft",
        is_featured=False,
        is_pinned=False,
        meta_title=original.meta_title,
        meta_description=original.meta_description,
        views_count=0,
        published_at=None,
    )
    db.session.add(duplicated)
    db.session.commit()

    _log_admin_action("blog_duplicate", {"source_post_id": original.id, "new_post_id": duplicated.id})
    flash("Post duplicated.", "success")

    if _wants_json_response():
        return jsonify({"success": True, "post_id": duplicated.id, "redirect_url": url_for("admin.blog_edit", id=duplicated.id)})
    return redirect(url_for("admin.blog_edit", id=duplicated.id))


@admin_bp.post("/blog/<int:id>/archive")
@login_required
@admin_required
def blog_archive(id):
    post = BlogPost.query.filter(BlogPost.deleted_at.is_(None), BlogPost.id == id).first_or_404()
    post.status = "archived"
    db.session.commit()
    _log_admin_action("blog_archive", {"post_id": id})

    if _wants_json_response():
        return jsonify({"success": True, "status": post.status})

    flash("Post archived.", "info")
    return redirect(url_for("admin.blog"))


@admin_bp.post("/blog/<int:id>/toggle-featured")
@login_required
@admin_required
def blog_toggle_featured(id):
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 400

    post = BlogPost.query.get_or_404(id)
    post.is_featured = not bool(post.is_featured)
    db.session.commit()
    _log_admin_action("blog_toggle_featured", {"post_id": id, "is_featured": post.is_featured})
    return jsonify({"success": True, "is_featured": bool(post.is_featured)})


@admin_bp.post("/blog/<int:id>/toggle-pinned")
@login_required
@admin_required
def blog_toggle_pinned(id):
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 400

    post = BlogPost.query.get_or_404(id)
    post.is_pinned = not bool(post.is_pinned)
    db.session.commit()
    _log_admin_action("blog_toggle_pinned", {"post_id": id, "is_pinned": post.is_pinned})
    return jsonify({"success": True, "is_pinned": bool(post.is_pinned)})


@admin_bp.get("/blog/<int:id>/preview")
@login_required
@admin_required
def blog_preview(id):
    post = BlogPost.query.filter(BlogPost.deleted_at.is_(None), BlogPost.id == id).first_or_404()
    token = _generate_blog_preview_token(post.id)
    return redirect(url_for("main.blog_post", slug=post.slug, preview_token=token))


@admin_bp.get("/blog/categories")
@login_required
@admin_required
def blog_categories():
    rows = (
        db.session.query(
            BlogPost.category,
            func.count(BlogPost.id),
            func.coalesce(func.sum(BlogPost.views_count), 0),
            func.coalesce(func.avg(BlogPost.reading_time_minutes), 0),
            func.max(BlogPost.published_at),
        )
        .filter(BlogPost.deleted_at.is_(None))
        .group_by(BlogPost.category)
        .all()
    )

    stats_map = {
        row[0]: {
            "post_count": int(row[1] or 0),
            "total_views": int(row[2] or 0),
            "avg_reading_time": round(float(row[3] or 0), 1),
            "last_post_date": row[4],
        }
        for row in rows
    }

    categories = []
    for category in BLOG_CATEGORIES:
        bucket = stats_map.get(category, {})
        categories.append(
            {
                "key": category,
                "label": BLOG_CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                "post_count": bucket.get("post_count", 0),
                "total_views": bucket.get("total_views", 0),
                "avg_reading_time": bucket.get("avg_reading_time", 0.0),
                "last_post_date": bucket.get("last_post_date"),
            }
        )

    return render_template("admin/blog_categories.html", categories=categories)


@admin_bp.route("/blog/tags", methods=["GET", "POST"])
@login_required
@admin_required
def blog_tags():
    if request.method == "POST":
        action = strip_html(request.form.get("action", ""), 40).strip().lower()
        target_tag = strip_html(request.form.get("target_tag", ""), 40).strip().lower()
        replacement_tag = strip_html(request.form.get("replacement_tag", ""), 40).strip().lower()

        if not target_tag:
            flash("Please select a tag first.", "warning")
            return redirect(url_for("admin.blog_tags"))

        posts = BlogPost.query.filter(BlogPost.deleted_at.is_(None)).all()
        affected_posts = 0
        for post in posts:
            current_tags = normalize_tags(post.tags or [], max_tags=50)
            if target_tag not in current_tags:
                continue

            if action == "rename" and replacement_tag:
                updated_tags = [replacement_tag if tag == target_tag else tag for tag in current_tags]
                post.tags = normalize_tags(updated_tags, max_tags=10)
                affected_posts += 1
            elif action == "delete":
                post.tags = [tag for tag in current_tags if tag != target_tag][:10]
                affected_posts += 1

        if affected_posts > 0:
            db.session.commit()
            _log_admin_action(
                "blog_tags_bulk_update",
                {
                    "action": action,
                    "target_tag": target_tag,
                    "replacement_tag": replacement_tag,
                    "affected_posts": affected_posts,
                },
            )
            if action == "rename" and replacement_tag:
                flash(f"Renamed tag '{target_tag}' to '{replacement_tag}' across {affected_posts} posts.", "success")
            else:
                flash(f"Removed tag '{target_tag}' from {affected_posts} posts.", "success")
        else:
            flash("No posts were updated.", "info")

        return redirect(url_for("admin.blog_tags"))

    selected_tag = strip_html(request.args.get("tag", ""), 40).strip().lower()

    posts = BlogPost.query.filter(BlogPost.deleted_at.is_(None)).order_by(BlogPost.updated_at.desc()).all()
    tag_counter = Counter()
    for post in posts:
        for tag in normalize_tags(post.tags or [], max_tags=50):
            tag_counter[tag] += 1

    max_count = max(tag_counter.values(), default=1)
    tag_cloud = []
    for tag, count in sorted(tag_counter.items(), key=lambda item: (-item[1], item[0])):
        font_scale = 0.9 + (count / max_count) * 1.4
        tag_cloud.append({"tag": tag, "count": count, "font_scale": round(font_scale, 2)})

    tagged_posts = []
    if selected_tag:
        tagged_posts = [post for post in posts if selected_tag in normalize_tags(post.tags or [], max_tags=50)]

    return render_template(
        "admin/blog_tags.html",
        tag_cloud=tag_cloud,
        selected_tag=selected_tag,
        tagged_posts=tagged_posts,
        category_labels=BLOG_CATEGORY_LABELS,
    )


@admin_bp.post("/blog/upload-cover")
@login_required
@admin_required
def blog_upload_cover():
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 400

    file_obj = request.files.get("file")
    if not file_obj or not file_obj.filename:
        return jsonify({"success": False, "error": "No file selected."}), 400

    try:
        raw_data = file_obj.read()
        file_obj.seek(0)
        if len(raw_data) > 5 * 1024 * 1024:
            raise FileHandlerError("Cover image must be under 5MB.")

        storage_path = upload_file_to_s3(
            file_obj,
            file_obj.filename,
            allowed_types={"image/jpeg", "image/png", "image/webp"},
        )
        return jsonify(
            {
                "success": True,
                "storage_path": storage_path,
                "url": generate_presigned_url(storage_path),
            }
        )
    except FileHandlerError as error:
        return jsonify({"success": False, "error": str(error)}), 400


@admin_bp.post("/blog/upload-inline-image")
@login_required
@admin_required
def blog_upload_inline_image():
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 400

    file_obj = request.files.get("file")
    if not file_obj or not file_obj.filename:
        return jsonify({"success": False, "error": "No file selected."}), 400

    try:
        raw_data = file_obj.read()
        file_obj.seek(0)
        if len(raw_data) > 5 * 1024 * 1024:
            raise FileHandlerError("Inline image must be under 5MB.")

        storage_path = upload_file_to_s3(
            file_obj,
            file_obj.filename,
            allowed_types={"image/jpeg", "image/png", "image/webp"},
        )
        return jsonify(
            {
                "success": True,
                "storage_path": storage_path,
                "url": generate_presigned_url(storage_path),
            }
        )
    except FileHandlerError as error:
        return jsonify({"success": False, "error": str(error)}), 400


@admin_bp.get("/templates")
@login_required
@admin_required
def templates():
    q = request.args.get("q", "").strip()
    query = ActionTemplate.query
    if q:
        query = query.filter(ActionTemplate.title.ilike(f"%{q}%"))

    pagination = _paginate(query.order_by(ActionTemplate.updated_at.desc()))
    return render_template("admin/templates.html", pagination=pagination, q=q)


@admin_bp.post("/templates/<int:id>/upgrade")
@login_required
@admin_required
def template_upgrade(id):
    template = ActionTemplate.query.get_or_404(id)
    tier = strip_html(request.form.get("quality_tier", "silver"), 20).lower()
    if tier not in {"bronze", "silver", "gold"}:
        tier = "silver"
    template.quality_tier = tier
    db.session.commit()
    flash(f"Template upgraded to {tier.title()}.", "success")
    return redirect(url_for("admin.templates"))


@admin_bp.post("/templates/<int:id>/unpublish")
@login_required
@admin_required
def template_unpublish(id):
    template = ActionTemplate.query.get_or_404(id)
    template.is_published = False
    db.session.commit()
    flash("Template unpublished.", "info")
    return redirect(url_for("admin.templates"))


@admin_bp.post("/templates/<int:id>/tier")
@login_required
@admin_required
def template_tier(id):
    return template_upgrade(id)


@admin_bp.get("/challenges")
@login_required
@admin_required
def challenges():
    pagination = _paginate(CivicChallenge.query.order_by(CivicChallenge.created_at.desc()))
    return render_template("admin/challenges.html", pagination=pagination)


@admin_bp.get("/users")
@login_required
@admin_required
def users():
    account_type = request.args.get("account_type", "").strip()
    subscription_tier = request.args.get("subscription_tier", "").strip()
    is_verified = request.args.get("is_verified", "").strip().lower()
    is_admin_filter = request.args.get("is_admin", "").strip().lower()
    q = request.args.get("q", "").strip()

    query = User.query
    if account_type:
        query = query.filter_by(account_type=account_type)
    if subscription_tier:
        query = query.filter_by(subscription_tier=subscription_tier)
    if is_verified in {"true", "false"}:
        query = query.filter_by(is_verified=(is_verified == "true"))
    if is_admin_filter in {"true", "false"}:
        query = query.filter_by(is_admin=(is_admin_filter == "true"))
    if q:
        query = query.filter(
            or_(
                User.email.ilike(f"%{q}%"),
                User.first_name.ilike(f"%{q}%"),
                User.last_name.ilike(f"%{q}%"),
                User.username.ilike(f"%{q}%"),
            )
        )

    pagination = _paginate(query.order_by(User.created_at.desc()))
    return render_template("admin/users.html", pagination=pagination)


@admin_bp.post("/users/<int:id>/disable")
@login_required
@admin_required
def disable_user(id):
    user = User.query.get_or_404(id)
    user.is_disabled = True
    db.session.commit()
    flash("User account disabled.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/enable")
@login_required
@admin_required
def enable_user(id):
    user = User.query.get_or_404(id)
    user.is_disabled = False
    db.session.commit()
    flash("User account re-enabled.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/grant-admin")
@login_required
@admin_required
def grant_admin(id):
    user = User.query.get_or_404(id)
    user.is_admin = True
    db.session.commit()
    flash("Admin access granted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/revoke-admin")
@login_required
@admin_required
def revoke_admin(id):
    user = User.query.get_or_404(id)
    user.is_admin = False
    db.session.commit()
    flash("Admin access revoked.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:id>/toggle-admin")
@login_required
@admin_required
def toggle_admin(id):
    user = User.query.get_or_404(id)
    if user.is_admin:
        user.is_admin = False
        message = "Admin access revoked."
        category = "info"
    else:
        user.is_admin = True
        message = "Admin access granted."
        category = "success"
    db.session.commit()
    flash(message, category)
    return redirect(url_for("admin.users"))


@admin_bp.get("/organizations")
@login_required
@admin_required
def organizations():
    pagination = _paginate(OrganizationAccount.query.order_by(OrganizationAccount.org_name.asc()))
    return render_template("admin/organizations.html", pagination=pagination)


@admin_bp.post("/organizations/<int:id>/verify")
@login_required
@admin_required
def verify_organization(id):
    org = OrganizationAccount.query.get_or_404(id)
    org.is_verified = True
    db.session.commit()
    flash("Organization verified.", "success")
    return redirect(url_for("admin.organizations"))


@admin_bp.post("/organizations/<int:id>/revoke")
@login_required
@admin_required
def revoke_organization_verification(id):
    org = OrganizationAccount.query.get_or_404(id)
    org.is_verified = False
    db.session.commit()
    flash("Organization verification revoked.", "info")
    return redirect(url_for("admin.organizations"))


@admin_bp.get("/analytics")
@login_required
@admin_required
def analytics():
    range_key = request.args.get("range", "30d")
    if range_key not in ANALYTICS_RANGES:
        range_key = "30d"
    return render_template("admin/analytics.html", default_range=range_key)


def _apply_period_filter(query, column, start_dt, end_dt):
    if start_dt is not None:
        query = query.filter(column >= start_dt)
    if end_dt is not None:
        query = query.filter(column <= end_dt)
    return query


def _sparkline_counts(datetimes: list, start_dt, end_dt, segments: int = 7, cumulative: bool = False, baseline: int = 0):
    start_dt = _as_utc(start_dt)
    end_dt = _as_utc(end_dt)
    if start_dt is None or end_dt is None:
        return [0] * segments

    duration = max((end_dt - start_dt).total_seconds(), 1)
    bucket_size = duration / segments
    buckets = [0] * segments
    for item in datetimes:
        item = _as_utc(item)
        if not item:
            continue
        if item < start_dt or item > end_dt:
            continue
        offset = (item - start_dt).total_seconds()
        index = min(segments - 1, int(offset / bucket_size))
        buckets[index] += 1

    if cumulative:
        running = baseline
        points = []
        for value in buckets:
            running += value
            points.append(running)
        return points
    return buckets


def _sparkline_weighted(events: list[tuple], start_dt, end_dt, segments: int = 7):
    start_dt = _as_utc(start_dt)
    end_dt = _as_utc(end_dt)
    if start_dt is None or end_dt is None:
        return [0] * segments

    duration = max((end_dt - start_dt).total_seconds(), 1)
    bucket_size = duration / segments
    buckets = [0] * segments
    for dt_value, weight in events:
        dt_value = _as_utc(dt_value)
        if not dt_value:
            continue
        if dt_value < start_dt or dt_value > end_dt:
            continue
        offset = (dt_value - start_dt).total_seconds()
        index = min(segments - 1, int(offset / bucket_size))
        buckets[index] += int(weight or 0)
    return buckets


def _safe_pct(current_value, previous_value):
    pct = _pct_change(float(current_value or 0), float(previous_value or 0) if previous_value is not None else None)
    if pct is None:
        return {"value": None, "direction": "neutral"}
    if pct > 0:
        direction = "up"
    elif pct < 0:
        direction = "down"
    else:
        direction = "neutral"
    return {"value": pct, "direction": direction}


def _rating_average_map():
    rows = (
        db.session.query(
            PeerRating.rated_user_id,
            func.avg((PeerRating.follow_through + PeerRating.collaboration + PeerRating.quality) / 3.0),
        )
        .group_by(PeerRating.rated_user_id)
        .all()
    )
    return {int(row[0]): float(row[1] or 0) for row in rows}


@admin_bp.get("/analytics/data")
@login_required
@admin_required
def analytics_data():
    try:
        period = _build_period_config(request.args.get("range", "30d"))
        range_key = period["key"]
        start_dt = period["start"]
        end_dt = period["end"]
        prev_start = period["previous_start"]
        prev_end = period["previous_end"]
        bucket_mode = period["bucket_mode"]

        user_query = User.query
        signup_query = _apply_period_filter(User.query, User.created_at, start_dt, end_dt)
        signup_prev_query = _apply_period_filter(User.query, User.created_at, prev_start, prev_end)

        total_users = _apply_period_filter(user_query, User.created_at, None, end_dt).count()
        previous_total_users = _apply_period_filter(user_query, User.created_at, None, prev_end).count() if prev_end else None
        new_signups = signup_query.count()
        new_signups_prev = signup_prev_query.count() if prev_start and prev_end else None

        active_project_statuses = ["active", "assembling"]
        active_projects = _apply_period_filter(
            Project.query.filter(Project.status.in_(active_project_statuses)),
            Project.created_at,
            None,
            end_dt,
        ).count()
        active_projects_prev = (
            _apply_period_filter(
                Project.query.filter(Project.status.in_(active_project_statuses)),
                Project.created_at,
                None,
                prev_end,
            ).count()
            if prev_end
            else None
        )

        completed_projects = _apply_period_filter(
            Project.query.filter(Project.status == "completed"),
            Project.updated_at,
            start_dt,
            end_dt,
        ).count()
        completed_projects_prev = (
            _apply_period_filter(Project.query.filter(Project.status == "completed"), Project.updated_at, prev_start, prev_end).count()
            if prev_start and prev_end
            else None
        )

        civic_actions_taken = _apply_period_filter(
            Task.query.filter(Task.status == "done", Task.completed_at.isnot(None)),
            Task.completed_at,
            start_dt,
            end_dt,
        ).count()
        civic_actions_prev = (
            _apply_period_filter(
                Task.query.filter(Task.status == "done", Task.completed_at.isnot(None)),
                Task.completed_at,
                prev_start,
                prev_end,
            ).count()
            if prev_start and prev_end
            else None
        )

        peer_ratings_submitted = _apply_period_filter(PeerRating.query, PeerRating.created_at, start_dt, end_dt).count()
        peer_ratings_prev = (
            _apply_period_filter(PeerRating.query, PeerRating.created_at, prev_start, prev_end).count() if prev_start and prev_end else None
        )

        ai_calls = _apply_period_filter(AIUsageLog.query, AIUsageLog.called_at, start_dt, end_dt).count()
        ai_calls_prev = (
            _apply_period_filter(AIUsageLog.query, AIUsageLog.called_at, prev_start, prev_end).count() if prev_start and prev_end else None
        )

        revenue_current = (
            _apply_period_filter(
                RazorpayPayment.query.filter(RazorpayPayment.was_verified.is_(True)),
                RazorpayPayment.paid_at,
                start_dt,
                end_dt,
            )
            .with_entities(func.coalesce(func.sum(RazorpayPayment.amount_inr), 0))
            .scalar()
            or 0
        )
        revenue_prev = (
            _apply_period_filter(
                RazorpayPayment.query.filter(RazorpayPayment.was_verified.is_(True)),
                RazorpayPayment.paid_at,
                prev_start,
                prev_end,
            )
            .with_entities(func.coalesce(func.sum(RazorpayPayment.amount_inr), 0))
            .scalar()
            if prev_start and prev_end
            else None
        )

        signups_for_spark = [row.created_at for row in signup_query.with_entities(User.created_at).all()]
        baseline_users = _apply_period_filter(User.query, User.created_at, None, start_dt).count() if start_dt else 0

        completed_for_spark = [
            row.updated_at
            for row in _apply_period_filter(
                Project.query.filter(Project.status == "completed"),
                Project.updated_at,
                start_dt,
                end_dt,
            )
            .with_entities(Project.updated_at)
            .all()
        ]
        tasks_done_for_spark = [
            row.completed_at
            for row in _apply_period_filter(
                Task.query.filter(Task.status == "done", Task.completed_at.isnot(None)),
                Task.completed_at,
                start_dt,
                end_dt,
            )
            .with_entities(Task.completed_at)
            .all()
        ]
        ratings_for_spark = [row.created_at for row in _apply_period_filter(PeerRating.query, PeerRating.created_at, start_dt, end_dt).with_entities(PeerRating.created_at).all()]
        ai_for_spark = [row.called_at for row in _apply_period_filter(AIUsageLog.query, AIUsageLog.called_at, start_dt, end_dt).with_entities(AIUsageLog.called_at).all()]
        revenue_events = [
            (row.paid_at, row.amount_inr)
            for row in _apply_period_filter(
                RazorpayPayment.query.filter(RazorpayPayment.was_verified.is_(True)),
                RazorpayPayment.paid_at,
                start_dt,
                end_dt,
            )
            .with_entities(RazorpayPayment.paid_at, RazorpayPayment.amount_inr)
            .all()
        ]

        kpis = [
            {
                "id": "total_users",
                "label": "Total Registered Users",
                "value": int(total_users),
                "change": _safe_pct(total_users, previous_total_users),
                "sparkline": _sparkline_counts(signups_for_spark, start_dt, end_dt, cumulative=True, baseline=baseline_users),
                "icon": "bi-people-fill",
                "tone": "green",
            },
            {
                "id": "new_signups",
                "label": "New Signups",
                "value": int(new_signups),
                "change": _safe_pct(new_signups, new_signups_prev),
                "sparkline": _sparkline_counts(signups_for_spark, start_dt, end_dt),
                "icon": "bi-person-plus-fill",
                "tone": "mint",
            },
            {
                "id": "active_projects",
                "label": "Active Projects",
                "value": int(active_projects),
                "change": _safe_pct(active_projects, active_projects_prev),
                "sparkline": _sparkline_counts(
                    [row.created_at for row in Project.query.filter(Project.status.in_(active_project_statuses)).with_entities(Project.created_at).all()],
                    start_dt,
                    end_dt,
                    cumulative=True,
                ),
                "icon": "bi-kanban-fill",
                "tone": "green",
            },
            {
                "id": "projects_completed",
                "label": "Projects Completed",
                "value": int(completed_projects),
                "change": _safe_pct(completed_projects, completed_projects_prev),
                "sparkline": _sparkline_counts(completed_for_spark, start_dt, end_dt),
                "icon": "bi-check2-circle",
                "tone": "mint",
            },
            {
                "id": "civic_actions",
                "label": "Civic Actions Taken",
                "value": int(civic_actions_taken),
                "change": _safe_pct(civic_actions_taken, civic_actions_prev),
                "sparkline": _sparkline_counts(tasks_done_for_spark, start_dt, end_dt),
                "icon": "bi-lightning-charge-fill",
                "tone": "orange",
            },
            {
                "id": "peer_ratings",
                "label": "Total Peer Ratings Submitted",
                "value": int(peer_ratings_submitted),
                "change": _safe_pct(peer_ratings_submitted, peer_ratings_prev),
                "sparkline": _sparkline_counts(ratings_for_spark, start_dt, end_dt),
                "icon": "bi-star-fill",
                "tone": "green",
            },
            {
                "id": "ai_feature_calls",
                "label": "AI Feature Calls",
                "value": int(ai_calls),
                "change": _safe_pct(ai_calls, ai_calls_prev),
                "sparkline": _sparkline_counts(ai_for_spark, start_dt, end_dt),
                "icon": "bi-cpu-fill",
                "tone": "mint",
            },
            {
                "id": "revenue_inr",
                "label": "Subscription Revenue (INR)",
                "value": int(revenue_current),
                "change": _safe_pct(revenue_current, revenue_prev),
                "sparkline": _sparkline_weighted(revenue_events, start_dt, end_dt),
                "icon": "bi-currency-rupee",
                "tone": "orange",
            },
        ]

        bucket_keys, bucket_labels = _build_bucket_labels(start_dt, end_dt, bucket_mode)

        signups_counter = Counter(_bucket_key(row.created_at, bucket_mode) for row in signup_query.with_entities(User.created_at).all())
        baseline_total_users = _apply_period_filter(User.query, User.created_at, None, start_dt).count() if start_dt else 0
        total_user_series = []
        running_total_users = baseline_total_users
        new_signups_series = []
        for key in bucket_keys:
            growth = int(signups_counter.get(key, 0))
            running_total_users += growth
            total_user_series.append(running_total_users)
            new_signups_series.append(growth)

        projects_created_counter = Counter(
            _bucket_key(row.created_at, bucket_mode)
            for row in _apply_period_filter(Project.query, Project.created_at, start_dt, end_dt).with_entities(Project.created_at).all()
        )
        projects_launched_counter = Counter(
            _bucket_key(row.updated_at, bucket_mode)
            for row in _apply_period_filter(
                Project.query.filter(Project.status == "active"),
                Project.updated_at,
                start_dt,
                end_dt,
            ).with_entities(Project.updated_at).all()
        )
        projects_completed_counter = Counter(
            _bucket_key(row.updated_at, bucket_mode)
            for row in _apply_period_filter(
                Project.query.filter(Project.status == "completed"),
                Project.updated_at,
                start_dt,
                end_dt,
            ).with_entities(Project.updated_at).all()
        )

        project_activity_created = [int(projects_created_counter.get(key, 0)) for key in bucket_keys]
        project_activity_launched = [int(projects_launched_counter.get(key, 0)) for key in bucket_keys]
        project_activity_completed = [int(projects_completed_counter.get(key, 0)) for key in bucket_keys]

        status_order = ["draft", "assembling", "launch_ready", "active", "completed", "archived"]
        status_rows = (
            db.session.query(Project.status, func.count(Project.id))
            .filter(Project.created_at <= end_dt)
            .group_by(Project.status)
            .all()
        )
        status_counts = {row[0]: int(row[1] or 0) for row in status_rows}
        status_distribution = [status_counts.get(status, 0) for status in status_order]

        domain_labels = {
            "environment": "Environment",
            "community": "Community",
            "education": "Education",
            "health": "Health",
            "civic_infrastructure": "Civic Infrastructure",
            "digital_access": "Digital Access",
            "food": "Food",
            "housing": "Housing",
            "other": "Other",
        }
        domain_rows = (
            db.session.query(Project.domain, func.count(Project.id))
            .filter(Project.created_at <= end_dt)
            .group_by(Project.domain)
            .all()
        )
        domain_counts = {row[0]: int(row[1] or 0) for row in domain_rows}
        ordered_domain_keys = list(domain_labels.keys())
        domain_counts_series = [domain_counts.get(domain_key, 0) for domain_key in ordered_domain_keys]
        domain_total = max(1, sum(domain_counts_series))
        domain_percentages = [round((count / domain_total) * 100.0, 2) for count in domain_counts_series]

        projects_for_geo = (
            _apply_period_filter(Project.query.options(joinedload(Project.roles)), Project.created_at, start_dt, end_dt)
            .order_by(Project.created_at.desc())
            .all()
        )
        geo_map = {}
        for project in projects_for_geo:
            country = (project.country or "").strip() or "Unknown"
            city = (project.city or "").strip()
            key = (country, city)
            bucket = geo_map.setdefault(
                key,
                {
                    "country": country,
                    "city": city,
                    "projects": 0,
                    "contributors": set(),
                    "completed_projects": 0,
                },
            )
            bucket["projects"] += 1
            if project.status == "completed":
                bucket["completed_projects"] += 1
            if project.creator_user_id:
                bucket["contributors"].add(project.creator_user_id)
            for role in project.roles:
                if role.filled_by_user_id:
                    bucket["contributors"].add(role.filled_by_user_id)

        geo_rows = []
        for value in geo_map.values():
            location = f"{value['city']}, {value['country']}" if value["city"] else value["country"]
            geo_rows.append(
                {
                    "location": location,
                    "country": value["country"],
                    "city": value["city"],
                    "projects": int(value["projects"]),
                    "contributors": len(value["contributors"]),
                    "completed_projects": int(value["completed_projects"]),
                }
            )

        geo_rows.sort(key=lambda row: (row["projects"], row["contributors"]), reverse=True)
        geo_top = geo_rows[:15]
        for idx, row in enumerate(geo_top, start=1):
            row["rank"] = idx

        skill_category_keys = ["technical", "professional", "community", "operational"]
        skill_category_counts = {key: 0 for key in skill_category_keys}

        users_for_skills = User.query.options(joinedload(User.skills)).all()
        for user in users_for_skills:
            categories_seen = set()
            for skill in user.skills:
                raw = (skill.category or "").strip().lower()
                if raw in skill_category_keys:
                    categories_seen.add(raw)
                elif any(token in raw for token in ["tech", "data", "digital", "software"]):
                    categories_seen.add("technical")
                elif any(token in raw for token in ["community", "social", "outreach", "public"]):
                    categories_seen.add("community")
                elif any(token in raw for token in ["operations", "logistics", "admin"]):
                    categories_seen.add("operational")
                else:
                    categories_seen.add("professional")
            for key in categories_seen:
                skill_category_counts[key] += 1

        applications_in_period = _apply_period_filter(RoleApplication.query, RoleApplication.applied_at, start_dt, end_dt)
        funnel_total = applications_in_period.count()
        funnel_pending = applications_in_period.filter(RoleApplication.status == "pending").count()
        funnel_accepted = applications_in_period.filter(RoleApplication.status.in_(["accepted", "approved"])).count()
        funnel_declined = applications_in_period.filter(RoleApplication.status == "declined").count()
        conversion_rate = round((funnel_accepted / funnel_total) * 100.0, 2) if funnel_total else 0.0

        task_created_counter = Counter(
            _bucket_key(row.created_at, bucket_mode)
            for row in _apply_period_filter(Task.query, Task.created_at, start_dt, end_dt).with_entities(Task.created_at).all()
        )
        task_done_counter = Counter(
            _bucket_key(row.completed_at, bucket_mode)
            for row in _apply_period_filter(
                Task.query.filter(Task.completed_at.isnot(None), Task.status == "done"),
                Task.completed_at,
                start_dt,
                end_dt,
            ).with_entities(Task.completed_at).all()
        )

        active_project_creation_counter = Counter(
            _bucket_key(row.created_at, bucket_mode)
            for row in Project.query.filter(Project.status.in_(["active", "assembling", "launch_ready"]))
            .with_entities(Project.created_at)
            .all()
        )

        running_tasks_total = 0
        running_tasks_done = 0
        running_active_projects = 0
        task_completion_series = []
        active_projects_series = []
        for key in bucket_keys:
            running_tasks_total += int(task_created_counter.get(key, 0))
            running_tasks_done += int(task_done_counter.get(key, 0))
            running_active_projects += int(active_project_creation_counter.get(key, 0))
            completion_pct = round((running_tasks_done / running_tasks_total) * 100.0, 2) if running_tasks_total else 0.0
            task_completion_series.append(completion_pct)
            active_projects_series.append(running_active_projects)

        month_keys, month_labels = _build_bucket_labels(start_dt, end_dt, "month")
        payments_in_period = _apply_period_filter(
            RazorpayPayment.query.filter(RazorpayPayment.was_verified.is_(True)),
            RazorpayPayment.paid_at,
            start_dt,
            end_dt,
        ).all()
        revenue_month_plan = defaultdict(int)
        for payment in payments_in_period:
            plan = _normalize_plan_key(payment.plan_name)
            if not plan:
                continue
            month_key = _bucket_key(payment.paid_at, "month")
            revenue_month_plan[(plan, month_key)] += int(payment.amount_inr or 0)

        revenue_creator_series = [revenue_month_plan[("creator_pro", key)] for key in month_keys]
        revenue_org_starter_series = [revenue_month_plan[("org_starter", key)] for key in month_keys]
        revenue_org_team_series = [revenue_month_plan[("org_team", key)] for key in month_keys]

        creator_price = int((current_app.config.get("RAZORPAY_CREATOR_PRO_AMOUNT", 74900) or 74900) / 100)
        org_starter_price = int((current_app.config.get("RAZORPAY_ORG_STARTER_AMOUNT", 499900) or 499900) / 100)
        org_team_price = int((current_app.config.get("RAZORPAY_ORG_TEAM_AMOUNT", 1499900) or 1499900) / 100)

        creator_subscribers = User.query.filter(User.subscription_tier == "creator_pro", User.is_premium.is_(True)).count()
        org_starter_subscribers = OrganizationAccount.query.filter(OrganizationAccount.subscription_tier == "org_starter").count()
        org_team_subscribers = OrganizationAccount.query.filter(OrganizationAccount.subscription_tier == "org_team").count()
        total_mrr = (
            creator_subscribers * creator_price
            + org_starter_subscribers * org_starter_price
            + org_team_subscribers * org_team_price
        )

        # If selected period has no payment events, show current MRR snapshot so chart remains informative.
        if not any(revenue_creator_series) and not any(revenue_org_starter_series) and not any(revenue_org_team_series):
            month_labels = ["Current MRR Snapshot"]
            revenue_creator_series = [creator_subscribers * creator_price]
            revenue_org_starter_series = [org_starter_subscribers * org_starter_price]
            revenue_org_team_series = [org_team_subscribers * org_team_price]

        ai_usage_counts = defaultdict(int)
        ai_rows = _apply_period_filter(AIUsageLog.query, AIUsageLog.called_at, start_dt, end_dt).with_entities(AIUsageLog.feature_name).all()
        for row in ai_rows:
            feature_name = _normalize_ai_feature_key(row.feature_name)
            if feature_name:
                ai_usage_counts[feature_name] += 1

        ai_feature_order = list(AI_FEATURE_LABELS.keys())
        ai_feature_series = [ai_usage_counts.get(key, 0) for key in ai_feature_order]

        # Backfill from all-time logs when period data is empty to avoid blank distribution charts.
        if sum(ai_feature_series) == 0:
            ai_usage_counts = defaultdict(int)
            all_time_ai_rows = AIUsageLog.query.with_entities(AIUsageLog.feature_name).all()
            for row in all_time_ai_rows:
                feature_name = _normalize_ai_feature_key(row.feature_name)
                if feature_name:
                    ai_usage_counts[feature_name] += 1
            ai_feature_series = [ai_usage_counts.get(key, 0) for key in ai_feature_order]

        blog_query = BlogPost.query.filter(BlogPost.deleted_at.is_(None))
        if start_dt:
            blog_query = blog_query.filter(or_(BlogPost.published_at.is_(None), BlogPost.published_at >= start_dt))
        top_blog_posts = blog_query.order_by(BlogPost.views_count.desc(), BlogPost.updated_at.desc()).limit(10).all()

        blog_labels = [post.title[:36] + ("..." if len(post.title) > 36 else "") for post in top_blog_posts]
        blog_views = [int(post.views_count or 0) for post in top_blog_posts]
        blog_reading_times = [int(post.reading_time_minutes or 0) for post in top_blog_posts]

        sent_notes = _apply_period_filter(
            Notification.query.filter(Notification.notification_type == "weekly_digest_sent"),
            Notification.created_at,
            start_dt,
            end_dt,
        ).with_entities(Notification.created_at).all()
        open_notes = _apply_period_filter(
            Notification.query.filter(Notification.notification_type == "weekly_digest_opened"),
            Notification.created_at,
            start_dt,
            end_dt,
        ).with_entities(Notification.created_at).all()

        week_keys = []
        week_labels = []
        week_cursor = datetime(start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc)
        while week_cursor <= end_dt:
            iso_year, iso_week, _ = week_cursor.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
            week_keys.append(key)
            week_labels.append(f"W{iso_week}")
            week_cursor += timedelta(days=7)

        sent_week_counter = Counter(
            f"{row.created_at.isocalendar().year}-W{row.created_at.isocalendar().week:02d}" for row in sent_notes if row.created_at
        )
        open_week_counter = Counter(
            f"{row.created_at.isocalendar().year}-W{row.created_at.isocalendar().week:02d}" for row in open_notes if row.created_at
        )
        weekly_sent_series = [int(sent_week_counter.get(key, 0)) for key in week_keys]
        weekly_open_series = [int(open_week_counter.get(key, 0)) for key in week_keys]

        rating_map = _rating_average_map()
        contributors = User.query.options(joinedload(User.skills)).order_by(User.projects_completed.desc(), User.created_at.asc()).limit(100).all()
        contributor_rows = []
        for user in contributors:
            contributor_rows.append(
                {
                    "user_id": user.id,
                    "name": user.full_name,
                    "username": user.username,
                    "profile_link": url_for("profile.public_profile", username=user.username),
                    "avatar_url": generate_presigned_url(user.profile_photo_url) if user.profile_photo_url else "",
                    "projects_completed": int(user.projects_completed or 0),
                    "peer_rating_average": round(float(rating_map.get(user.id, 0.0)), 2),
                    "skills_count": len(user.skills),
                    "account_created": user.created_at.isoformat() if user.created_at else None,
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                }
            )
        contributor_rows.sort(
            key=lambda row: (row["projects_completed"], row["peer_rating_average"], row["skills_count"]),
            reverse=True,
        )
        contributor_rows = contributor_rows[:20]
        for idx, row in enumerate(contributor_rows, start=1):
            row["rank"] = idx

        projects_for_activity = Project.query.options(joinedload(Project.tasks), joinedload(Project.milestones), joinedload(Project.roles), joinedload(Project.creator)).all()
        project_rows = []
        for project in projects_for_activity:
            tasks_total = len(project.tasks)
            tasks_done = sum(1 for task in project.tasks if task.status == "done")
            team_size = 1 + sum(1 for role in project.roles if role.is_filled and role.filled_by_user_id)
            if project.milestones:
                milestone_progress_values = []
                for milestone in project.milestones:
                    raw_progress = float(milestone.completion_pct or 0.0)
                    # Support both legacy [0,1] fractions and [0,100] percentage values.
                    if 0.0 < raw_progress <= 1.0:
                        raw_progress *= 100.0
                    milestone_progress_values.append(max(0.0, min(100.0, raw_progress)))
                milestone_progress = round(sum(milestone_progress_values) / len(milestone_progress_values), 2)
            else:
                milestone_progress = 0.0
            activity_score = tasks_done * 3 + tasks_total
            project_rows.append(
                {
                    "project_id": project.id,
                    "title": project.title,
                    "project_link": url_for("projects_public.detail", id=project.id),
                    "domain": project.domain,
                    "status": project.status,
                    "creator_name": project.creator.full_name if project.creator else "Unknown",
                    "team_size": team_size,
                    "tasks_completed": tasks_done,
                    "tasks_total": tasks_total,
                    "milestone_progress": milestone_progress,
                    "started_date": project.start_date.isoformat() if project.start_date else None,
                    "activity_score": activity_score,
                }
            )
        project_rows.sort(key=lambda row: (row["activity_score"], row["tasks_completed"]), reverse=True)
        project_rows = project_rows[:15]

        events = []

        for user in User.query.order_by(User.created_at.desc()).limit(30).all():
            if user.created_at:
                events.append(
                    {
                        "icon": "bi-person-plus",
                        "description": "New user signup",
                        "user": user.full_name,
                        "timestamp": user.created_at,
                        "link": url_for("profile.public_profile", username=user.username),
                    }
                )

        for project in Project.query.filter(Project.is_published.is_(True)).order_by(Project.created_at.desc()).limit(30).all():
            if project.created_at:
                events.append(
                    {
                        "icon": "bi-megaphone",
                        "description": f"Project published: {project.title}",
                        "user": project.creator.full_name if project.creator else "",
                        "timestamp": project.created_at,
                        "link": url_for("projects_public.detail", id=project.id),
                    }
                )

        for project in Project.query.filter(Project.status == "completed").order_by(Project.updated_at.desc()).limit(30).all():
            if project.updated_at:
                events.append(
                    {
                        "icon": "bi-check2-square",
                        "description": f"Project completed: {project.title}",
                        "user": project.creator.full_name if project.creator else "",
                        "timestamp": project.updated_at,
                        "link": url_for("projects_public.detail", id=project.id),
                    }
                )

        for outcome in ProjectOutcome.query.filter(ProjectOutcome.is_published.is_(True)).order_by(ProjectOutcome.submitted_at.desc()).limit(30).all():
            if outcome.submitted_at and outcome.project:
                events.append(
                    {
                        "icon": "bi-award",
                        "description": f"Outcome approved: {outcome.project.title}",
                        "user": outcome.project.creator.full_name if outcome.project and outcome.project.creator else "",
                        "timestamp": outcome.submitted_at,
                        "link": url_for("admin.outcome_detail", id=outcome.id),
                    }
                )

        for org in OrganizationAccount.query.options(joinedload(OrganizationAccount.owner)).limit(30).all():
            owner_created = org.owner.created_at if org.owner else None
            if owner_created:
                events.append(
                    {
                        "icon": "bi-buildings",
                        "description": f"New organization account: {org.org_name}",
                        "user": org.owner.full_name if org.owner else "",
                        "timestamp": owner_created,
                        "link": url_for("admin.organizations"),
                    }
                )

        for payment in RazorpayPayment.query.filter(RazorpayPayment.was_verified.is_(True)).order_by(RazorpayPayment.paid_at.desc()).limit(30).all():
            if payment.paid_at:
                plan_key = _normalize_plan_key(payment.plan_name)
                events.append(
                    {
                        "icon": "bi-currency-rupee",
                        "description": f"New subscription payment: {SUBSCRIPTION_PLAN_LABELS.get(plan_key, payment.plan_name)}",
                        "user": payment.user.full_name if payment.user else "",
                        "timestamp": payment.paid_at,
                        "link": url_for("settings.billing"),
                    }
                )

        for log_row in AIUsageLog.query.order_by(AIUsageLog.called_at.desc()).limit(30).all():
            if log_row.called_at:
                feature_key = _normalize_ai_feature_key(log_row.feature_name)
                feature_label = AI_FEATURE_LABELS.get(feature_key, (log_row.feature_name or "AI feature").replace("_", " ").title())
                events.append(
                    {
                        "icon": "bi-cpu",
                        "description": f"AI feature used: {feature_label}",
                        "user": log_row.user.full_name if log_row.user else "",
                        "timestamp": log_row.called_at,
                        "link": url_for("admin.analytics"),
                    }
                )

        for challenge in CivicChallenge.query.order_by(CivicChallenge.created_at.desc()).limit(30).all():
            if challenge.created_at:
                events.append(
                    {
                        "icon": "bi-lightbulb",
                        "description": f"New civic challenge posted: {challenge.title}",
                        "user": challenge.organization.org_name if challenge.organization else "",
                        "timestamp": challenge.created_at,
                        "link": url_for("admin.challenges"),
                    }
                )

        events.sort(key=lambda event: event["timestamp"], reverse=True)
        event_feed = []
        for event in events[:50]:
            event_feed.append(
                {
                    "icon": event["icon"],
                    "description": event["description"],
                    "user": event.get("user", ""),
                    "timestamp": event["timestamp"].isoformat() if event.get("timestamp") else None,
                    "link": event.get("link", ""),
                }
            )

        data = {
            "success": True,
            "range": range_key,
            "kpis": kpis,
            "charts": {
                "user_growth": {
                    "labels": bucket_labels,
                    "total_users": total_user_series,
                    "new_signups": new_signups_series,
                },
                "project_activity": {
                    "labels": bucket_labels,
                    "created": project_activity_created,
                    "launched": project_activity_launched,
                    "completed": project_activity_completed,
                },
                "project_status_distribution": {
                    "labels": [PROJECT_STATUS_LABELS.get(status, status.replace("_", " ").title()) for status in status_order],
                    "keys": status_order,
                    "values": status_distribution,
                    "total": int(sum(status_distribution)),
                    "links": [url_for("admin.projects", status=status) for status in status_order],
                },
                "domain_distribution": {
                    "labels": [domain_labels[key] for key in ordered_domain_keys],
                    "values": domain_counts_series,
                    "percentages": domain_percentages,
                },
                "geographic_distribution": {
                    "labels": [row["location"] for row in geo_top],
                    "values": [row["projects"] for row in geo_top],
                    "table": geo_top,
                },
                "skill_category_distribution": {
                    "labels": ["Technical", "Professional", "Community", "Operational"],
                    "values": [skill_category_counts[key] for key in skill_category_keys],
                },
                "application_funnel": {
                    "labels": ["Total Role Applications", "Pending", "Accepted", "Declined"],
                    "values": [funnel_total, funnel_pending, funnel_accepted, funnel_declined],
                    "conversion_rate": conversion_rate,
                },
                "task_completion_rate": {
                    "labels": bucket_labels,
                    "completion_rate": task_completion_series,
                    "active_projects": active_projects_series,
                },
                "revenue_breakdown": {
                    "labels": month_labels,
                    "creator_pro": revenue_creator_series,
                    "org_starter": revenue_org_starter_series,
                    "org_team": revenue_org_team_series,
                    "summary": {
                        "creator_pro_subscribers": creator_subscribers,
                        "org_starter_subscribers": org_starter_subscribers,
                        "org_team_subscribers": org_team_subscribers,
                        "total_mrr_inr": int(total_mrr),
                    },
                },
                "ai_usage_distribution": {
                    "labels": [AI_FEATURE_LABELS[key] for key in ai_feature_order],
                    "values": ai_feature_series,
                },
                "blog_performance": {
                    "labels": blog_labels,
                    "views": blog_views,
                    "reading_time": blog_reading_times,
                    "table": [
                        {
                            "title": post.title,
                            "category": BLOG_CATEGORY_LABELS.get(post.category, post.category.replace("_", " ").title()),
                            "views": int(post.views_count or 0),
                            "published_date": post.published_at.isoformat() if post.published_at else None,
                            "reading_time": int(post.reading_time_minutes or 0),
                            "featured": bool(post.is_featured),
                            "slug": post.slug,
                        }
                        for post in top_blog_posts
                    ],
                },
                "weekly_digest_engagement": {
                    "labels": week_labels,
                    "sent": weekly_sent_series,
                    "opens": weekly_open_series,
                    "has_open_data": any(value > 0 for value in weekly_open_series),
                },
            },
            "tables": {
                "top_contributors": contributor_rows,
                "most_active_projects": project_rows,
                "recent_events": event_feed,
            },
        }

        return jsonify(data), 200

    except Exception as error:
        logger.exception("analytics_data_failed error=%s", str(error))
        return jsonify({"success": False, "error": "Failed to build analytics data."}), 500


@admin_bp.get("/email-logs")
@login_required
@admin_required
def email_logs():
    type_filter = request.args.get("email_type", "").strip()
    status_filter = request.args.get("status", "").strip()

    query = Notification.query
    if type_filter:
        query = query.filter(Notification.notification_type.ilike(f"%{type_filter}%"))

    pagination = _paginate(query.order_by(Notification.created_at.desc()))
    return render_template(
        "admin/email_logs.html",
        pagination=pagination,
        type_filter=type_filter,
        status_filter=status_filter,
    )


@admin_bp.post("/email-logs/<int:id>/resend")
@login_required
@admin_required
def resend_email_log(id):
    Notification.query.get_or_404(id)
    flash("Email resend queued.", "success")
    return redirect(url_for("admin.email_logs"))
