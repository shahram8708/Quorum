from app.extensions import db
from app.utils import utcnow


class OrganizationAccount(db.Model):
    __tablename__ = "organization_accounts"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    org_name = db.Column(db.String(300), nullable=False)
    org_type = db.Column(db.String(100), nullable=False)
    org_domain = db.Column(db.String(200), nullable=False)
    mission_description = db.Column(db.Text, nullable=False)
    logo_url = db.Column(db.String(500))
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    subscription_tier = db.Column(db.String(50), default="org_starter", nullable=False)
    monthly_challenge_credits = db.Column(db.Integer, default=0, nullable=False)
    total_projects_supported = db.Column(db.Integer, default=0, nullable=False)

    owner = db.relationship("User")
    supported_projects = db.relationship("Project", foreign_keys="Project.org_support_id")
    challenges = db.relationship("CivicChallenge", back_populates="organization", cascade="all, delete-orphan")


class CivicChallenge(db.Model):
    __tablename__ = "civic_challenges"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization_accounts.id"), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=False)
    domain = db.Column(db.String(100), nullable=False)
    geographic_scope = db.Column(db.String(200), nullable=False)
    grant_amount_inr = db.Column(db.Integer)
    deadline = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), default="open", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    organization = db.relationship("OrganizationAccount", back_populates="challenges")
