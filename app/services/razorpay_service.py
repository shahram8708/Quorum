import json

import razorpay
from flask import current_app


class RazorpayService:
    def __init__(self):
        self.client = razorpay.Client(
            auth=(
                current_app.config.get("RAZORPAY_KEY_ID"),
                current_app.config.get("RAZORPAY_KEY_SECRET"),
            )
        )

    def get_subscription_plans(self):
        return {
            "free": {"label": "Individual", "amount": 0, "currency": "INR"},
            "creator_pro": {
                "label": "Creator Pro",
                "amount": current_app.config["RAZORPAY_CREATOR_PRO_AMOUNT"],
                "currency": "INR",
            },
            "org_starter": {
                "label": "Org Starter",
                "amount": current_app.config["RAZORPAY_ORG_STARTER_AMOUNT"],
                "currency": "INR",
            },
            "org_team": {
                "label": "Org Team",
                "amount": current_app.config["RAZORPAY_ORG_TEAM_AMOUNT"],
                "currency": "INR",
            },
            "enterprise": {"label": "Enterprise", "amount": None, "currency": "INR"},
        }

    def create_order(self, amount_inr: int, plan: str):
        amount_paise = int(amount_inr)
        order = self.client.order.create(
            {
                "amount": amount_paise,
                "currency": "INR",
                "payment_capture": 1,
                "notes": {"plan": plan},
            }
        )
        return {
            "order_id": order["id"],
            "amount": amount_paise,
            "currency": order.get("currency", "INR"),
            "razorpay_key_id": current_app.config.get("RAZORPAY_KEY_ID"),
        }

    def verify_payment(self, razorpay_order_id, razorpay_payment_id, razorpay_signature):
        payload = {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        }
        try:
            self.client.utility.verify_payment_signature(payload)
            return True
        except razorpay.errors.SignatureVerificationError:
            return False

    def handle_webhook(self, payload, signature):
        secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
        body = payload if isinstance(payload, str) else payload.decode("utf-8")
        self.client.utility.verify_webhook_signature(body, signature, secret)
        event = json.loads(body)
        return event.get("event", "unknown")
