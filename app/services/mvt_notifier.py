from app.extensions import db
from app.models import Notification, Project, ProjectRole, User
from app.services.email_service import send_mvt_alert
from app.services.skill_matcher import find_matching_contributors
from app.utils import utcnow


def check_mvt(project_id):
    project = Project.query.get_or_404(project_id)
    filled_count = ProjectRole.query.filter_by(project_id=project.id, is_filled=True).count()

    if filled_count >= project.min_viable_team_size and project.status == "assembling":
        project.status = "launch_ready"
        db.session.commit()
        send_mvt_alerts(project.id)
        return True
    return False


def _create_notification(user_id, notification_type, title, message, link):
    note = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link=link,
        created_at=utcnow(),
    )
    db.session.add(note)


def send_mvt_alerts(project_id):
    project = Project.query.get_or_404(project_id)

    creator = User.query.get(project.creator_user_id)
    if creator:
        _create_notification(
            creator.id,
            "mvt_reached",
            "Your project is ready to launch",
            f"{project.title} reached the minimum viable team threshold.",
            f"/my-projects/{project.id}/manage",
        )
        send_mvt_alert(creator, project)

    matches = find_matching_contributors(project_id)
    user_ids = set()
    for users in matches.values():
        for user in users:
            user_ids.add(user.id)

    for user_id in user_ids:
        _create_notification(
            user_id,
            "mvt_reached",
            f"Project is almost ready: {project.title}",
            "A project in your skill area is nearing launch.",
            f"/projects/{project.id}",
        )

    db.session.commit()
