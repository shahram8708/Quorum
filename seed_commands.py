import json
from datetime import date, timedelta
from pathlib import Path

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models import (
    PeerRating,
    Project,
    ProjectMilestone,
    ProjectOutcome,
    ProjectRole,
    Skill,
    Task,
    User,
)
from app.utils import utcnow


BASE_DIR = Path(__file__).resolve().parent


def register_seed_commands(app):
    app.cli.add_command(seed_skills_command)
    app.cli.add_command(seed_projects_command)


def seed_skills_data() -> tuple[int, int]:
    path = BASE_DIR / "seed_data" / "skills_taxonomy.json"
    records = json.loads(path.read_text(encoding="utf-8"))

    inserted = 0
    updated = 0

    for row in records:
        skill = Skill.query.filter_by(name=row["name"]).first()
        if not skill:
            skill = Skill(
                id=row.get("id"),
                name=row["name"],
                category=row["category"],
                domain_relevance=row.get("domain_relevance", []),
                is_active=bool(row.get("is_active", True)),
            )
            db.session.add(skill)
            inserted += 1
        else:
            skill.category = row["category"]
            skill.domain_relevance = row.get("domain_relevance", [])
            skill.is_active = bool(row.get("is_active", True))
            updated += 1

    db.session.commit()
    return inserted, updated


def seed_projects_data() -> int:
    skills = Skill.query.all()
    if not skills:
        return 0

    path = BASE_DIR / "seed_data" / "seed_projects.json"
    projects_payload = json.loads(path.read_text(encoding="utf-8"))

    created_projects = 0

    for index, payload in enumerate(projects_payload, start=1):
        existing = Project.query.filter_by(title=payload["title"]).first()
        if existing:
            continue

        creator_email = f"creator{index}@quorum.local"
        creator = User.query.filter_by(email=creator_email).first()
        if not creator:
            creator = User(
                email=creator_email,
                username=f"creator_{index}",
                first_name=f"Creator{index}",
                last_name="Quorum",
                account_type="individual",
                is_verified=True,
                onboarding_complete=True,
                city=payload["city"],
                country=payload["country"],
                domain_interests=[payload["domain"]],
            )
            creator.set_password("ChangeMeSecure123")
            creator.skills = skills[index : index + 5]
            db.session.add(creator)
            db.session.flush()

        project = Project(
            creator_user_id=creator.id,
            title=payload["title"],
            problem_statement=(
                f"{payload['title']} addresses a high-priority local challenge in {payload['city']}. "
                "The project combines structured delivery, community participation, and measurable milestones."
            ),
            project_type=payload["project_type"],
            success_definition=(
                "Project success is defined by role fulfillment, milestone completion, and measurable local outcomes "
                "validated by beneficiary feedback and team reporting."
            ),
            geographic_scope=payload["geographic_scope"],
            city=payload["city"],
            country=payload["country"],
            domain=payload["domain"],
            timeline_days=int(payload["timeline_days"]),
            start_date=date.today() - timedelta(days=20),
            end_date=date.today() + timedelta(days=max(10, int(payload["timeline_days"]) - 20)),
            min_viable_team_size=max(2, min(4, len(payload.get("roles", [])))),
            status=payload["status"],
            resources_needed=["volunteers", "local_partners", "operational_budget"],
            estimated_budget="INR 2L - INR 8L",
            is_published=True,
            completion_pct=0.0,
        )
        db.session.add(project)
        db.session.flush()

        member_users = []
        for team_idx, team_name in enumerate(payload.get("team", []), start=1):
            first_name, *rest = team_name.split(" ")
            last_name = " ".join(rest) if rest else "Member"
            member_email = f"member_{index}_{team_idx}@quorum.local"
            member = User.query.filter_by(email=member_email).first()
            if not member:
                member = User(
                    email=member_email,
                    username=f"member_{index}_{team_idx}",
                    first_name=first_name,
                    last_name=last_name,
                    account_type="individual",
                    is_verified=True,
                    onboarding_complete=True,
                    city=payload["city"],
                    country=payload["country"],
                    domain_interests=[payload["domain"]],
                )
                member.set_password("ChangeMeSecure123")
                member.skills = skills[(index + team_idx) : (index + team_idx + 5)]
                db.session.add(member)
                db.session.flush()
            member_users.append(member)

        for role_idx, role_payload in enumerate(payload.get("roles", [])):
            matched_skill_ids = [
                skill.id
                for skill in Skill.query.filter(Skill.name.in_(role_payload.get("skills", []))).all()
            ]
            assigned_member = member_users[role_idx] if role_idx < len(member_users) else None

            role = ProjectRole(
                project_id=project.id,
                title=role_payload["title"],
                description=(
                    f"Responsible for {role_payload['title'].lower()} execution within the project delivery cycle."
                ),
                skill_tags=matched_skill_ids,
                hours_per_week=float(role_payload.get("hours_per_week", 5)),
                is_filled=assigned_member is not None,
                filled_by_user_id=assigned_member.id if assigned_member else None,
                accepted_at=utcnow() if assigned_member else None,
                is_mvt_required=True,
            )
            db.session.add(role)

        db.session.flush()

        for ms_idx, milestone_payload in enumerate(payload.get("milestones", []), start=1):
            milestone = ProjectMilestone(
                project_id=project.id,
                title=milestone_payload["title"],
                description=f"Milestone {ms_idx} delivery plan",
                target_date=project.start_date + timedelta(days=ms_idx * 20),
                order_index=ms_idx,
                completion_pct=0.0,
            )
            db.session.add(milestone)
            db.session.flush()

            for task_idx, task_title in enumerate(milestone_payload.get("tasks", []), start=1):
                assignee = member_users[(task_idx - 1) % len(member_users)] if member_users else None
                task = Task(
                    project_id=project.id,
                    milestone_id=milestone.id,
                    title=task_title,
                    description=f"Execution task for {milestone.title}",
                    assigned_to_user_id=assignee.id if assignee else None,
                    created_by_user_id=creator.id,
                    due_date=milestone.target_date - timedelta(days=3),
                    priority="normal",
                    status="done" if payload["status"] == "completed" else "todo",
                    completed_at=utcnow() if payload["status"] == "completed" else None,
                    version=0,
                )
                db.session.add(task)

        if payload["status"] == "completed":
            project.completion_pct = 100.0
            outcome = ProjectOutcome(
                project_id=project.id,
                outcome_achieved=(
                    "Project achieved meaningful measurable outcomes with strong team collaboration "
                    "and consistent stakeholder engagement."
                ),
                measurable_data="Milestone targets reached and beneficiary feedback improved.",
                team_size_actual=max(2, len(member_users) + 1),
                total_hours_estimated=420,
                unexpected_challenges="Coordination delays and seasonal disruption required timeline adjustments.",
                lessons_learned="Early stakeholder alignment and weekly check-ins improved delivery confidence.",
                would_recommend=True,
                was_continued=True,
                continuation_description="Partner organizations are continuing implementation in adjacent areas.",
                submitted_at=utcnow(),
                is_published=True,
                outcome_rating="partial_success",
            )
            db.session.add(outcome)

            for rated_user in member_users:
                rating = PeerRating(
                    project_id=project.id,
                    rater_user_id=creator.id,
                    rated_user_id=rated_user.id,
                    follow_through=4,
                    collaboration=5,
                    quality=4,
                    testimonial="Consistently reliable and collaborative.",
                    created_at=utcnow(),
                )
                db.session.add(rating)

        created_projects += 1

    db.session.commit()
    return created_projects


@click.command("seed-skills")
@with_appcontext
def seed_skills_command():
    inserted, updated = seed_skills_data()
    click.echo(f"Seeded skills: inserted={inserted}, updated={updated}")


@click.command("seed-projects")
@with_appcontext
def seed_projects_command():
    created_projects = seed_projects_data()
    if created_projects == 0 and Skill.query.count() == 0:
        click.echo("Skills taxonomy is empty. Run 'flask seed-skills' first.")
        return
    click.echo(f"Seeded projects: created={created_projects}")
