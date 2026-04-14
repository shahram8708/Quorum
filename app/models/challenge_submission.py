from datetime import datetime

from app.extensions import db


class ChallengeSubmission(db.Model):
    __tablename__ = "challenge_submissions"

    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("civic_challenges.id"), nullable=False, index=True)
    submitter_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    team_name = db.Column(db.String(300), nullable=False)
    team_member_ids = db.Column(db.JSON, default=list, nullable=False)
    approach_summary = db.Column(db.Text, nullable=False)
    linked_project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    proposal_document_path = db.Column(db.String(500), nullable=True)
    proposal_document_url = db.Column(db.String(500), nullable=True)
    external_link = db.Column(db.String(500), nullable=True)

    status = db.Column(db.String(50), default="submitted", nullable=False)
    org_feedback = db.Column(db.Text, nullable=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)

    submitted_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    challenge = db.relationship(
        "CivicChallenge",
        back_populates="submissions",
        foreign_keys=[challenge_id],
    )
    submitter = db.relationship("User", foreign_keys=[submitter_user_id])
    linked_project = db.relationship("Project", foreign_keys=[linked_project_id])

    __table_args__ = (
        db.UniqueConstraint("challenge_id", "submitter_user_id", name="uq_challenge_submission"),
    )
