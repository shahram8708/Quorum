from app.extensions import db


class ProjectMilestone(db.Model):
    __tablename__ = "project_milestones"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    target_date = db.Column(db.Date, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))
    order_index = db.Column(db.Integer, default=0, nullable=False)
    completion_pct = db.Column(db.Float, default=0.0, nullable=False)

    project = db.relationship("Project", back_populates="milestones")
    tasks = db.relationship("Task", back_populates="milestone")
