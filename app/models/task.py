from app.extensions import db
from app.utils import utcnow


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    milestone_id = db.Column(db.Integer, db.ForeignKey("project_milestones.id"), index=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    due_date = db.Column(db.Date)
    priority = db.Column(db.String(50), default="normal", nullable=False)
    status = db.Column(db.String(50), default="todo", nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    version = db.Column(db.Integer, default=0, nullable=False)

    project = db.relationship("Project", back_populates="tasks")
    milestone = db.relationship("ProjectMilestone", back_populates="tasks")
    assignee = db.relationship("User", back_populates="assigned_tasks", foreign_keys=[assigned_to_user_id])
    created_by = db.relationship("User", back_populates="created_tasks", foreign_keys=[created_by_user_id])
