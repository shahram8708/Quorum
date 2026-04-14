import bcrypt
from flask_login import UserMixin

from app.extensions import db
from app.models.skill import UserSkill
from app.utils import utcnow


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100))
    username = db.Column(db.String(100), unique=True, nullable=False)
    account_type = db.Column(db.String(50), nullable=False, default="individual")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_login = db.Column(db.DateTime(timezone=True))
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    subscription_tier = db.Column(db.String(50), default="free", nullable=False)
    subscription_expires = db.Column(db.DateTime(timezone=True))
    razorpay_customer_id = db.Column(db.String(100))
    razorpay_subscription_id = db.Column(db.String(100))
    city = db.Column(db.String(200), default="")
    country = db.Column(db.String(100), default="")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    bio = db.Column(db.Text)
    profile_photo_url = db.Column(db.String(500))
    availability_hours = db.Column(db.Integer)
    is_open_to_projects = db.Column(db.Boolean, default=True, nullable=False)
    onboarding_complete = db.Column(db.Boolean, default=False, nullable=False)
    reputation_score = db.Column(db.Float)
    projects_completed = db.Column(db.Integer, default=0, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_disabled = db.Column(db.Boolean, default=False, nullable=False)
    domain_interests = db.Column(db.JSON, default=list, nullable=False)
    rating_count = db.Column(db.Integer, default=0, nullable=False)
    notification_preferences = db.Column(db.JSON, default=dict, nullable=False)

    skills = db.relationship("Skill", secondary=UserSkill, back_populates="users")

    created_projects = db.relationship("Project", back_populates="creator", foreign_keys="Project.creator_user_id")
    filled_roles = db.relationship("ProjectRole", back_populates="filled_by_user", foreign_keys="ProjectRole.filled_by_user_id")
    applications = db.relationship("RoleApplication", back_populates="applicant", foreign_keys="RoleApplication.applicant_user_id")
    assigned_tasks = db.relationship("Task", back_populates="assignee", foreign_keys="Task.assigned_to_user_id")
    created_tasks = db.relationship("Task", back_populates="created_by", foreign_keys="Task.created_by_user_id")
    feed_posts = db.relationship("FeedPost", back_populates="author", foreign_keys="FeedPost.author_user_id")
    ratings_given = db.relationship("PeerRating", back_populates="rater", foreign_keys="PeerRating.rater_user_id")
    ratings_received = db.relationship("PeerRating", back_populates="rated", foreign_keys="PeerRating.rated_user_id")
    notifications = db.relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def check_password(self, password: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))
        except Exception:
            return False

    def has_onboarding_inputs(self) -> bool:
        has_city = bool((self.city or "").strip())
        has_country = bool((self.country or "").strip())
        has_availability = isinstance(self.availability_hours, int) and self.availability_hours >= 1
        has_domain_interests = isinstance(self.domain_interests, list) and len(self.domain_interests) > 0
        has_skills = len(self.skills) > 0

        return bool(has_city and has_country and has_availability and has_domain_interests and has_skills)

    def has_completed_onboarding(self) -> bool:
        return bool(self.onboarding_complete and self.has_onboarding_inputs())

    @property
    def needs_onboarding(self) -> bool:
        if self.is_admin:
            return False
        return not self.has_completed_onboarding()

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name or ''}".strip()

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    notification_type = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="notifications")


class AICivicPulseCache(db.Model):
    __tablename__ = "ai_civic_pulse_cache"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    generated_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User")
