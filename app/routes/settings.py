from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import csrf, db
from app.routes import validate_ajax_csrf
from app.services.razorpay_service import RazorpayService
from app.utils import strip_html, utcnow


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        current_user.email = strip_html(request.form.get("email", current_user.email), 255).lower()
        current_user.username = strip_html(request.form.get("username", current_user.username), 100).lower()

        new_password = request.form.get("password", "")
        if new_password:
            if len(new_password) < 12:
                flash("Password must be at least 12 characters.", "danger")
                return render_template("settings/account.html")
            current_user.set_password(new_password)

        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("settings.account"))

    return render_template("settings/account.html")


@settings_bp.get("/billing")
@login_required
def billing():
    service = RazorpayService()
    plans = service.get_subscription_plans()
    return render_template("settings/billing.html", plans=plans)


@settings_bp.post("/billing/subscribe")
@login_required
def billing_subscribe():
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"error": "Invalid CSRF token"}), 400

    plan = strip_html((request.json or {}).get("plan", ""), 50)
    service = RazorpayService()
    plans = service.get_subscription_plans()

    if plan not in plans or plans[plan]["amount"] is None:
        return jsonify({"error": "Invalid plan"}), 400

    order = service.create_order(plans[plan]["amount"], plan)
    return jsonify(order)


@settings_bp.post("/billing/verify")
@login_required
def billing_verify():
    try:
        validate_ajax_csrf()
    except ValidationError:
        return jsonify({"error": "Invalid CSRF token"}), 400

    payload = request.json or {}
    service = RazorpayService()

    valid = service.verify_payment(
        payload.get("razorpay_order_id"),
        payload.get("razorpay_payment_id"),
        payload.get("razorpay_signature"),
    )

    if not valid:
        return jsonify({"success": False, "error": "signature_verification_failed"}), 400

    selected_plan = strip_html(payload.get("plan", "creator_pro"), 50)
    if selected_plan not in {"creator_pro", "org_starter", "org_team"}:
        selected_plan = "creator_pro"

    current_user.subscription_tier = selected_plan
    current_user.is_premium = selected_plan != "free"
    current_user.subscription_expires = utcnow() + timedelta(days=30)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "plan": selected_plan,
            "message": f"Subscription upgraded to {selected_plan.replace('_', ' ').title()}!",
        }
    )


@settings_bp.post("/billing/webhook")
@csrf.exempt
def billing_webhook():
    payload = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")

    service = RazorpayService()
    try:
        event_type = service.handle_webhook(payload, signature)
    except Exception:
        return jsonify({"status": "invalid_signature"}), 400

    return jsonify({"status": "ok", "event": event_type})


@settings_bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    prefs = current_user.notification_preferences or {
        "application_received": True,
        "application_accepted": True,
        "weekly_digest": True,
        "mvt_alert": True,
        "browser_push": False,
    }

    if request.method == "POST":
        prefs = {
            "application_received": bool(request.form.get("application_received")),
            "application_accepted": bool(request.form.get("application_accepted")),
            "weekly_digest": bool(request.form.get("weekly_digest")),
            "mvt_alert": bool(request.form.get("mvt_alert")),
            "browser_push": bool(request.form.get("browser_push")),
        }
        current_user.notification_preferences = prefs
        db.session.commit()
        flash("Notification preferences saved.", "success")
        return redirect(url_for("settings.notifications"))

    return render_template("settings/notifications.html", prefs=prefs)


@settings_bp.post("/delete")
@login_required
def delete_account():
    current_user.is_disabled = True
    db.session.commit()
    flash("Your account has been scheduled for deletion and disabled.", "info")
    return redirect(url_for("auth.logout"))
