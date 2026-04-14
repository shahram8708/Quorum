from app.extensions import db
from app.utils import utcnow


class AIUsageLog(db.Model):
    __tablename__ = "ai_usage_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    feature_name = db.Column(db.String(100), nullable=False, index=True)
    called_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    response_time_ms = db.Column(db.Integer)
    was_successful = db.Column(db.Boolean, nullable=False, default=True)
    tokens_estimated = db.Column(db.Integer)

    user = db.relationship("User", back_populates="ai_usage_logs")


class RazorpayPayment(db.Model):
    __tablename__ = "razorpay_payments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan_name = db.Column(db.String(50), nullable=False, index=True)
    amount_inr = db.Column(db.Integer, nullable=False)
    amount_paise = db.Column(db.Integer, nullable=False)
    razorpay_order_id = db.Column(db.String(100), index=True)
    razorpay_payment_id = db.Column(db.String(100), index=True)
    was_verified = db.Column(db.Boolean, nullable=False, default=False, index=True)
    paid_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    payment_meta = db.Column(db.JSON, default=dict, nullable=False)

    user = db.relationship("User", back_populates="payments")
