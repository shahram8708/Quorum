from collections import defaultdict

from app.models import Project, ProjectRole, User
from app.services.geo_matcher import haversine_distance


def _get_user_skill_ids(user):
    return {skill.id for skill in user.skills}


def _score_user_for_role(user, role, project):
    role_skills = set(role.skill_tags or [])
    overlap = len(_get_user_skill_ids(user).intersection(role_skills))

    reputation_bonus = (user.reputation_score or 0) * 2
    experience_bonus = min(5, user.projects_completed or 0)
    score = overlap * 10 + reputation_bonus + experience_bonus

    if project.geographic_scope in {"neighborhood", "city"}:
        if user.country and project.country and user.country.lower() == project.country.lower():
            score += 5
        if None not in [user.latitude, user.longitude, project.latitude, project.longitude]:
            distance = haversine_distance(project.latitude, project.longitude, user.latitude, user.longitude)
            if distance <= 100:
                score += max(0, int((100 - distance) / 10))

    return score


def find_matching_contributors(project_id):
    project = Project.query.get_or_404(project_id)
    users = User.query.filter(
        User.is_open_to_projects.is_(True),
        User.is_verified.is_(True),
        User.is_disabled.is_(False),
    ).all()

    role_matches = defaultdict(list)

    for role in project.roles:
        if role.is_filled:
            continue

        scored = []
        for user in users:
            if user.id == project.creator_user_id:
                continue
            score = _score_user_for_role(user, role, project)
            if score > 0:
                scored.append((score, user))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        role_matches[role.id] = [user for _score, user in scored[:20]]

    return dict(role_matches)
