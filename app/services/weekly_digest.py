from datetime import date, timedelta

from app.models import Project, ProjectRole, Task
from app.services.email_service import send_weekly_digest


def send_weekly_digest_for_project(project_id):
    project = Project.query.get_or_404(project_id)
    today = date.today()
    week_end = today + timedelta(days=7)
    week_start = today - timedelta(days=7)

    due_this_week = Task.query.filter(
        Task.project_id == project.id,
        Task.due_date >= today,
        Task.due_date <= week_end,
    ).count()

    done_last_week = Task.query.filter(
        Task.project_id == project.id,
        Task.completed_at.isnot(None),
        Task.completed_at >= week_start,
    ).count()

    overdue = Task.query.filter(
        Task.project_id == project.id,
        Task.status != "done",
        Task.due_date < today,
    ).count()

    milestone_count = len([m for m in project.milestones if m.target_date and today <= m.target_date <= week_end])

    digest_data = {
        "due_this_week": due_this_week,
        "done_last_week": done_last_week,
        "overdue": overdue,
        "milestones": milestone_count,
    }

    team_member_ids = {project.creator_user_id}
    team_member_ids.update(
        role.filled_by_user_id for role in ProjectRole.query.filter_by(project_id=project.id, is_filled=True).all() if role.filled_by_user_id
    )

    for user_id in team_member_ids:
        from app.models import User  # local import to avoid cycles

        user = User.query.get(user_id)
        if user:
            send_weekly_digest(user, project, digest_data)


def run_weekly_digest_for_all_projects():
    projects = Project.query.filter_by(status="active").all()
    for project in projects:
        send_weekly_digest_for_project(project.id)
