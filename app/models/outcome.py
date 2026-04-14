from app.extensions import db
from app.utils import utcnow


class ProjectOutcome(db.Model):
    __tablename__ = "project_outcomes"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), unique=True, nullable=False, index=True)
    outcome_achieved = db.Column(db.Text, nullable=False)
    measurable_data = db.Column(db.Text)
    team_size_actual = db.Column(db.Integer, nullable=False)
    total_hours_estimated = db.Column(db.Integer, nullable=False)
    unexpected_challenges = db.Column(db.Text, nullable=False)
    lessons_learned = db.Column(db.Text, nullable=False)
    would_recommend = db.Column(db.Boolean, nullable=False)
    was_continued = db.Column(db.Boolean, nullable=False)
    continuation_description = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    outcome_rating = db.Column(db.String(50), default="partial_success", nullable=False)

    project = db.relationship("Project", back_populates="outcome")


class PeerRating(db.Model):
    __tablename__ = "peer_ratings"
    __table_args__ = (
        db.UniqueConstraint("project_id", "rater_user_id", "rated_user_id", name="uq_peer_rating"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    rater_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    rated_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    follow_through = db.Column(db.Integer, nullable=False)
    collaboration = db.Column(db.Integer, nullable=False)
    quality = db.Column(db.Integer, nullable=False)
    testimonial = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    rater = db.relationship("User", back_populates="ratings_given", foreign_keys=[rater_user_id])
    rated = db.relationship("User", back_populates="ratings_received", foreign_keys=[rated_user_id])
    project = db.relationship("Project")
