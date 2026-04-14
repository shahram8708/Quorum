from app.extensions import db
from app.utils import utcnow


BLOG_CATEGORIES = [
    "civic_action",
    "platform_updates",
    "success_stories",
    "guides_and_tips",
    "organizations",
    "announcements",
]

BLOG_STATUSES = ["draft", "published", "archived"]


class BlogPost(db.Model):
    __tablename__ = "blog_posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    slug = db.Column(db.String(600), unique=True, index=True, nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False, default="civic_action")
    tags = db.Column(db.JSON, default=list, nullable=False)
    cover_image_url = db.Column(db.String(500))
    cover_image_alt = db.Column(db.String(300))
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False, default="")
    reading_time_minutes = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(50), nullable=False, default="draft")
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)
    meta_title = db.Column(db.String(200))
    meta_description = db.Column(db.String(300))
    views_count = db.Column(db.Integer, nullable=False, default=0)
    published_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True))

    author = db.relationship("User", back_populates="blog_posts", foreign_keys=[author_user_id])

    def __repr__(self) -> str:
        return f"<BlogPost {self.slug}>"
