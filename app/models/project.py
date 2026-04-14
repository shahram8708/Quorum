from app.extensions import db
from app.utils import utcnow


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    creator_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    problem_statement = db.Column(db.Text, nullable=False)
    project_type = db.Column(db.String(100), nullable=False)
    success_definition = db.Column(db.Text, nullable=False)
    geographic_scope = db.Column(db.String(50), nullable=False)
    city = db.Column(db.String(200), default="")
    country = db.Column(db.String(100), default="")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    domain = db.Column(db.String(100), nullable=False)
    timeline_days = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    min_viable_team_size = db.Column(db.Integer, default=2, nullable=False)
    status = db.Column(db.String(50), default="draft", nullable=False)
    resources_needed = db.Column(db.JSON, default=list, nullable=False)
    estimated_budget = db.Column(db.String(100), default="")
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    is_flagged = db.Column(db.Boolean, default=False, nullable=False)
    flag_reason = db.Column(db.Text)
    is_template_source = db.Column(db.Boolean, default=False, nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey("action_templates.id"))
    org_support_id = db.Column(db.Integer, db.ForeignKey("organization_accounts.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    completion_pct = db.Column(db.Float, default=0.0, nullable=False)

    creator = db.relationship("User", back_populates="created_projects", foreign_keys=[creator_user_id])
    roles = db.relationship("ProjectRole", back_populates="project", cascade="all, delete-orphan")
    milestones = db.relationship("ProjectMilestone", back_populates="project", cascade="all, delete-orphan")
    tasks = db.relationship("Task", back_populates="project", cascade="all, delete-orphan")
    feed_posts = db.relationship("FeedPost", back_populates="project", cascade="all, delete-orphan")
    applications = db.relationship("RoleApplication", back_populates="project", cascade="all, delete-orphan")
    outcome = db.relationship("ProjectOutcome", back_populates="project", uselist=False, cascade="all, delete-orphan")
    templates = db.relationship("ActionTemplate", back_populates="source_project", foreign_keys="ActionTemplate.source_project_id")


class ProjectRole(db.Model):
    __tablename__ = "project_roles"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=False)
    skill_tags = db.Column(db.JSON, default=list, nullable=False)
    hours_per_week = db.Column(db.Float, default=4.0, nullable=False)
    is_filled = db.Column(db.Boolean, default=False, nullable=False)
    filled_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    accepted_at = db.Column(db.DateTime(timezone=True))
    is_mvt_required = db.Column(db.Boolean, default=False, nullable=False)

    project = db.relationship("Project", back_populates="roles")
    filled_by_user = db.relationship("User", back_populates="filled_roles", foreign_keys=[filled_by_user_id])
    applications = db.relationship("RoleApplication", back_populates="role", cascade="all, delete-orphan")


class RoleApplication(db.Model):
    __tablename__ = "role_applications"
    __table_args__ = (
        db.UniqueConstraint("role_id", "applicant_user_id", name="uq_role_user_application"),
    )

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("project_roles.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    applicant_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    application_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default="pending", nullable=False)
    applied_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    decline_message = db.Column(db.Text)

    role = db.relationship("ProjectRole", back_populates="applications")
    project = db.relationship("Project", back_populates="applications")
    applicant = db.relationship("User", back_populates="applications", foreign_keys=[applicant_user_id])
