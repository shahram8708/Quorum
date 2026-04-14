from datetime import datetime, timezone

from app.extensions import db
from app.models import PeerRating, Project, ProjectRole, User
from sqlalchemy import or_


def recompute_reputation(user_id: int):
    ratings = (
        PeerRating.query.filter_by(rated_user_id=user_id)
        .order_by(PeerRating.created_at.desc())
        .all()
    )

    user = User.query.get(user_id)
    if not user:
        return None

    user.rating_count = len(ratings)

    if len(ratings) < 3:
        user.reputation_score = None
        db.session.commit()
        return None

    now = datetime.now(timezone.utc)
    weighted_sum = 0.0
    weight_total = 0.0

    for rating in ratings:
        age_days = max((now - rating.created_at).days, 0)
        recency_weight = max(0.4, 1.0 - (age_days / 3650.0))
        score = (rating.follow_through + rating.collaboration + rating.quality) / 3.0
        weighted_sum += score * recency_weight
        weight_total += recency_weight

    final_score = round(weighted_sum / weight_total, 2)
    user.reputation_score = final_score
    db.session.commit()
    return final_score


def get_completed_projects_for_user(user_id: int):
    return (
        Project.query.outerjoin(ProjectRole, ProjectRole.project_id == Project.id)
        .filter(
            Project.status == "completed",
            or_(Project.creator_user_id == user_id, ProjectRole.filled_by_user_id == user_id),
        )
        .order_by(Project.updated_at.desc())
        .distinct()
        .all()
    )


def update_badge_counts(user_id: int):
    user = User.query.get(user_id)
    if not user:
        return {}

    completed_projects = get_completed_projects_for_user(user_id)

    user.projects_completed = len(completed_projects)

    domain_counter = {}
    for project in completed_projects:
        domain = (project.domain or "").strip()
        if not domain:
            continue
        domain_counter[domain] = domain_counter.get(domain, 0) + 1

    badges = {
        "first_project": user.projects_completed >= 1,
        "five_projects": user.projects_completed >= 5,
        "ten_projects": user.projects_completed >= 10,
        "domain_expert": any(count >= 5 for count in domain_counter.values()),
    }

    db.session.commit()
    return badges
