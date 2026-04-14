from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import db
from app.forms.task_forms import TaskCreateForm
from app.models import Project, ProjectMilestone, Task
from app.routes import create_notification, team_member_required, validate_ajax_csrf
from app.utils import strip_html, utcnow


tasks_bp = Blueprint("tasks", __name__, url_prefix="/my-projects/<int:id>/tasks")


def _can_move_task(project, task):
    if project.creator_user_id == current_user.id:
        return True
    return task.assigned_to_user_id == current_user.id


def _recompute_progress(project):
    total_tasks = len(project.tasks)
    done_tasks = len([task for task in project.tasks if task.status == "done"])
    project.completion_pct = round((done_tasks / max(total_tasks, 1)) * 100, 2)

    for milestone in project.milestones:
        milestone_tasks = [task for task in project.tasks if task.milestone_id == milestone.id]
        if not milestone_tasks:
            milestone.completion_pct = 0.0
            continue
        done = len([task for task in milestone_tasks if task.status == "done"])
        milestone.completion_pct = round((done / len(milestone_tasks)) * 100, 2)

    db.session.commit()


@tasks_bp.get("")
@login_required
@team_member_required
def board(id):
    project = Project.query.get_or_404(id)
    can_create_tasks = current_user.id == project.creator_user_id
    members = [project.creator] + [role.filled_by_user for role in project.roles if role.filled_by_user]
    member_options = [(0, "Unassigned")] + [(member.id, member.full_name) for member in members if member]

    create_form = TaskCreateForm()
    create_form.assigned_to_user_id.choices = member_options

    assignee_filter = request.args.get("assignee", type=int)
    milestone_filter = request.args.get("milestone", type=int)

    tasks_query = Task.query.filter_by(project_id=id)
    if assignee_filter:
        tasks_query = tasks_query.filter_by(assigned_to_user_id=assignee_filter)
    if milestone_filter:
        tasks_query = tasks_query.filter_by(milestone_id=milestone_filter)

    tasks = tasks_query.order_by(Task.created_at.desc()).all()
    board_data = {
        "todo": [serialize_task(task) for task in tasks if task.status == "todo"],
        "in_progress": [serialize_task(task) for task in tasks if task.status == "in_progress"],
        "done": [serialize_task(task) for task in tasks if task.status == "done"],
    }

    milestones = ProjectMilestone.query.filter_by(project_id=id).order_by(ProjectMilestone.order_index.asc()).all()
    pending_applications_count = len([app for app in project.applications if app.status == "pending"])
    overdue_tasks_count = (
        Task.query.filter_by(project_id=id)
        .filter(Task.status != "done", Task.due_date.isnot(None), Task.due_date < date.today())
        .count()
    )

    return render_template(
        "tasks/board.html",
        project=project,
        tasks=tasks,
        board_data=board_data,
        create_form=create_form,
        milestones=milestones,
        active_tab="tasks",
        pending_applications_count=pending_applications_count,
        overdue_tasks_count=overdue_tasks_count,
        assignee_filter=assignee_filter,
        milestone_filter=milestone_filter,
        members=[member for member in members if member],
        can_create_tasks=can_create_tasks,
    )


@tasks_bp.post("/new")
@login_required
@team_member_required
def create_task(id):
    project = Project.query.get_or_404(id)
    members = [project.creator] + [role.filled_by_user for role in project.roles if role.filled_by_user]
    member_options = [(0, "Unassigned")] + [(member.id, member.full_name) for member in members if member]
    expects_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if current_user.id != project.creator_user_id:
        message = "Only the project creator can create tasks."
        if expects_json:
            return jsonify({"success": False, "message": message}), 403
        flash(message, "warning")
        return redirect(url_for("tasks.board", id=id))

    form = TaskCreateForm()
    form.assigned_to_user_id.choices = member_options

    if form.validate_on_submit():
        task = Task(
            project_id=id,
            title=strip_html(form.title.data, 500),
            description=strip_html(form.description.data or "", 2000),
            due_date=form.due_date.data,
            priority=form.priority.data,
            assigned_to_user_id=form.assigned_to_user_id.data or None,
            created_by_user_id=current_user.id,
            status="todo",
            version=0,
        )
        db.session.add(task)
        db.session.commit()

        if task.assigned_to_user_id:
            create_notification(
                task.assigned_to_user_id,
                "task_assigned",
                f"New task assigned: {task.title}",
                f"You were assigned a task in {project.title}.",
                f"/my-projects/{project.id}/tasks",
            )
            db.session.commit()

        success_message = "Task created successfully."
        if expects_json:
            return (
                jsonify(
                    {
                        "success": True,
                        "message": success_message,
                        "task_html": render_template("components/task_card.html", task=task, project=project),
                    }
                ),
                201,
            )

        flash(success_message, "success")
        return redirect(url_for("tasks.board", id=id))

    if expects_json:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Invalid task data.",
                    "errors": form.errors,
                }
            ),
            400,
        )

    flash("Could not create task. Please check the form and try again.", "danger")
    return redirect(url_for("tasks.board", id=id))


@tasks_bp.post("/<int:task_id>/status")
@login_required
@team_member_required
def update_task_status(id, task_id):
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"error": "csrf"}), 400

    project = Project.query.get_or_404(id)
    task = Task.query.filter_by(id=task_id, project_id=id).first_or_404()

    if not _can_move_task(project, task):
        return jsonify({"error": "forbidden"}), 403

    payload = request.json or {}
    new_status = payload.get("new_status")
    incoming_version = int(payload.get("version", -1))

    if incoming_version != task.version:
        return (
            jsonify(
                {
                    "error": "conflict",
                    "current_status": task.status,
                    "current_version": task.version,
                }
            ),
            409,
        )

    if new_status not in {"todo", "in_progress", "done"}:
        return jsonify({"error": "invalid_status"}), 400

    task.status = new_status
    if new_status == "done":
        task.completed_at = utcnow()
    else:
        task.completed_at = None
    task.version += 1

    if task.due_date and task.due_date < date.today() and new_status != "done" and task.assigned_to_user_id:
        create_notification(
            task.assigned_to_user_id,
            "task_overdue",
            f"Task overdue: {task.title}",
            "This task is now overdue.",
            f"/my-projects/{project.id}/tasks",
        )

    db.session.commit()
    _recompute_progress(project)

    return jsonify(
        {
            "success": True,
            "new_version": task.version,
            "project_completion_pct": project.completion_pct,
        }
    )


@tasks_bp.post("/<int:task_id>/complete")
@login_required
@team_member_required
def complete_task(id, task_id):
    project = Project.query.get_or_404(id)
    task = Task.query.filter_by(id=task_id, project_id=id).first_or_404()

    if current_user.id not in {task.assigned_to_user_id, project.creator_user_id}:
        return jsonify({"error": "forbidden"}), 403

    task.status = "done"
    task.completed_at = utcnow()
    task.version += 1
    db.session.commit()

    _recompute_progress(project)

    return jsonify({"success": True, "project_completion_pct": project.completion_pct})


def serialize_task(task):
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority,
        "assignee": task.assignee.full_name if task.assignee else "Unassigned",
        "assignee_id": task.assigned_to_user_id,
        "version": task.version,
        "milestone_id": task.milestone_id,
    }
