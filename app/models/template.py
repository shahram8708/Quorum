from app.extensions import db
from app.utils import utcnow


class ActionTemplate(db.Model):
    __tablename__ = "action_templates"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    domain = db.Column(db.String(100), nullable=False)
    source_project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    problem_archetype = db.Column(db.Text, nullable=False)
    recommended_team_size = db.Column(db.Integer, nullable=False)
    recommended_timeline_days = db.Column(db.Integer, nullable=False)
    recommended_roles = db.Column(db.JSON, default=list, nullable=False)
    recommended_milestones = db.Column(db.JSON, default=list, nullable=False)
    recommended_tasks = db.Column(db.JSON, default=list, nullable=False)
    common_challenges = db.Column(db.Text, nullable=False)
    resources_typically_needed = db.Column(db.JSON, default=list, nullable=False)
    estimated_budget_range = db.Column(db.String(100), nullable=False)
    times_used = db.Column(db.Integer, default=0, nullable=False)
    quality_tier = db.Column(db.String(50), default="bronze", nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    source_project = db.relationship("Project", back_populates="templates", foreign_keys=[source_project_id])
    linked_projects = db.relationship("Project", foreign_keys="Project.template_id")
