from sqlalchemy import or_

from app.models import Project
from app.services.geo_matcher import haversine_distance


def build_project_query(filters: dict, user=None):
    query = Project.query.filter_by(is_published=True)

    if filters.get("domain"):
        query = query.filter(Project.domain == filters["domain"])

    if filters.get("status"):
        query = query.filter(Project.status == filters["status"])

    if filters.get("geographic_scope"):
        query = query.filter(Project.geographic_scope == filters["geographic_scope"])

    if filters.get("keyword"):
        keyword = f"%{filters['keyword']}%"
        query = query.filter(or_(Project.title.ilike(keyword), Project.problem_statement.ilike(keyword)))

    projects = query.order_by(Project.created_at.desc()).all()

    skills_needed = filters.get("skills_needed") or []
    if skills_needed:
        skill_set = {int(skill_id) for skill_id in skills_needed}
        projects = [
            project
            for project in projects
            if any(skill_set.intersection(set(role.skill_tags or [])) for role in project.roles if not role.is_filled)
        ]

    sort = filters.get("sort", "newest")

    if sort == "most_urgent":
        projects.sort(
            key=lambda project: (sum(1 for role in project.roles if not role.is_filled) - project.min_viable_team_size),
        )
    elif sort == "near_me" and user and None not in [user.latitude, user.longitude]:
        projects.sort(
            key=lambda project: haversine_distance(
                user.latitude,
                user.longitude,
                project.latitude or 0,
                project.longitude or 0,
            )
        )
    elif sort == "highest_match" and user:
        user_skills = {skill.id for skill in user.skills}

        def score(project):
            overlap = 0
            for role in project.roles:
                if role.is_filled:
                    continue
                overlap += len(user_skills.intersection(set(role.skill_tags or [])))
            return overlap

        projects.sort(key=score, reverse=True)

    return projects
