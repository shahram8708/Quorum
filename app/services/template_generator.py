from app.extensions import db
from app.models import ActionTemplate, Project


def can_generate_template(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.outcome:
        return False
    return project.outcome.is_published and project.outcome.outcome_rating in {"full_success", "partial_success"}


def convert_to_template(project_id):
    project = Project.query.get_or_404(project_id)

    roles = [
        {
            "title": role.title,
            "description": role.description,
            "skill_tags": role.skill_tags,
            "hours_per_week": role.hours_per_week,
        }
        for role in project.roles
    ]
    milestones = [
        {
            "title": milestone.title,
            "description": milestone.description,
            "target_date": milestone.target_date.isoformat() if milestone.target_date else None,
            "order_index": milestone.order_index,
        }
        for milestone in project.milestones
    ]
    tasks = [
        {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "status": task.status,
        }
        for task in project.tasks
    ]

    template = ActionTemplate(
        title=f"Template: {project.title}",
        domain=project.domain,
        source_project_id=project.id,
        problem_archetype=project.problem_statement,
        recommended_team_size=max(project.min_viable_team_size, len(project.roles)),
        recommended_timeline_days=project.timeline_days,
        recommended_roles=roles,
        recommended_milestones=milestones,
        recommended_tasks=tasks,
        common_challenges=project.outcome.unexpected_challenges if project.outcome else "",
        resources_typically_needed=project.resources_needed,
        estimated_budget_range=project.estimated_budget or "Variable",
        quality_tier="bronze",
        is_published=True,
    )
    db.session.add(template)
    project.is_template_source = True
    db.session.commit()
    return template
