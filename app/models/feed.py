from app.extensions import db
from app.utils import utcnow


class FeedPost(db.Model):
    __tablename__ = "feed_posts"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parent_post_id = db.Column(db.Integer, db.ForeignKey("feed_posts.id"), index=True)
    content = db.Column(db.Text, nullable=False)
    is_decision = db.Column(db.Boolean, default=False, nullable=False)
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    file_attachments = db.Column(db.JSON, default=list, nullable=False)

    project = db.relationship("Project", back_populates="feed_posts")
    author = db.relationship("User", back_populates="feed_posts", foreign_keys=[author_user_id])
    parent = db.relationship("FeedPost", remote_side=[id], backref=db.backref("replies", cascade="all,delete-orphan"))
