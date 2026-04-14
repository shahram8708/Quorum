from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.feed_forms import FeedPostForm, FeedReplyForm
from app.models import FeedPost, Project, Task
from app.routes import team_member_required
from app.services.file_handler import (
    ALLOWED_MIME_TYPES,
    FileHandlerError,
    generate_presigned_url,
    upload_file_to_s3,
)
from app.utils import strip_html, utcnow


feed_bp = Blueprint("feed", __name__, url_prefix="/my-projects/<int:id>/feed")


@feed_bp.route("", methods=["GET", "POST"])
@login_required
@team_member_required
def index(id):
    project = Project.query.get_or_404(id)

    post_form = FeedPostForm()
    reply_form = FeedReplyForm()

    if post_form.validate_on_submit():
        attachments = []
        file = request.files.get("attachment")
        if file and file.filename:
            try:
                storage_path = upload_file_to_s3(file, file.filename, ALLOWED_MIME_TYPES)
                attachments.append(
                    {
                        "filename": file.filename,
                        "storage_path": storage_path,
                        "file_type": file.mimetype,
                        "presigned_url": generate_presigned_url(storage_path),
                    }
                )
            except FileHandlerError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("feed.index", id=id))

        post = FeedPost(
            project_id=id,
            author_user_id=current_user.id,
            content=strip_html(post_form.content.data, 2000),
            is_decision=post_form.is_decision.data,
            file_attachments=attachments,
            created_at=utcnow(),
        )
        db.session.add(post)
        db.session.commit()
        return redirect(url_for("feed.index", id=id))

    page = max(1, request.args.get("page", 1, type=int))
    decision_only = request.args.get("tab") == "decisions"

    query = FeedPost.query.filter_by(project_id=id, parent_post_id=None)
    if decision_only:
        query = query.filter_by(is_decision=True)

    pagination = query.order_by(FeedPost.is_pinned.desc(), FeedPost.created_at.desc()).paginate(
        page=page,
        per_page=20,
        error_out=False,
    )

    for post in pagination.items:
        post.file_attachments = _refresh_attachments(post.file_attachments)
        for reply in post.replies:
            reply.file_attachments = _refresh_attachments(reply.file_attachments)

    pending_applications_count = len([app for app in project.applications if app.status == "pending"])
    overdue_tasks_count = (
        Task.query.filter_by(project_id=id)
        .filter(Task.status != "done", Task.due_date.isnot(None), Task.due_date < date.today())
        .count()
    )

    return render_template(
        "feed/index.html",
        project=project,
        pagination=pagination,
        post_form=post_form,
        reply_form=reply_form,
        decision_only=decision_only,
        active_tab="feed",
        pending_applications_count=pending_applications_count,
        overdue_tasks_count=overdue_tasks_count,
    )


@feed_bp.post("/<int:post_id>/reply")
@login_required
@team_member_required
def reply(id, post_id):
    parent = FeedPost.query.filter_by(id=post_id, project_id=id).first_or_404()
    form = FeedReplyForm()

    if form.validate_on_submit():
        reply_post = FeedPost(
            project_id=id,
            author_user_id=current_user.id,
            parent_post_id=parent.id,
            content=strip_html(form.content.data, 2000),
            created_at=utcnow(),
        )
        db.session.add(reply_post)
        db.session.commit()

    return redirect(url_for("feed.index", id=id))


@feed_bp.post("/<int:post_id>/pin")
@login_required
@team_member_required
def pin(id, post_id):
    project = Project.query.get_or_404(id)
    if project.creator_user_id != current_user.id:
        return ("Forbidden", 403)

    post = FeedPost.query.filter_by(id=post_id, project_id=id).first_or_404()
    post.is_pinned = not post.is_pinned
    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json":
        return jsonify({"success": True, "is_pinned": post.is_pinned})
    return redirect(url_for("feed.index", id=id))


def _refresh_attachments(attachments):
    refreshed = []
    for item in attachments or []:
        refreshed.append(
            {
                "filename": item.get("filename"),
                "storage_path": item.get("storage_path"),
                "file_type": item.get("file_type"),
                "presigned_url": generate_presigned_url(item.get("storage_path")),
            }
        )
    return refreshed
