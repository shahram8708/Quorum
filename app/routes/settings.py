from datetime import timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError

from app.extensions import csrf, db
from app.models import OrganizationAccount, RazorpayPayment
from app.routes import validate_ajax_csrf
from app.services.razorpay_service import RazorpayService
from app.utils import strip_html, utcnow


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

ORG_SUBSCRIPTION_TIERS = {"org_starter", "org_team", "enterprise"}
ORG_DEFAULT_CHALLENGE_CREDITS = {
    "org_starter": 3,
    "org_team": 10,
    "enterprise": 25,
}


def _is_org_profile_complete(org_account: OrganizationAccount | None) -> bool:
    if not org_account:
        return False

    required_values = [
        org_account.org_name,
        org_account.org_type,
        org_account.org_domain,
        org_account.mission_description,
    ]
    return all(bool((value or "").strip()) for value in required_values)


def _safe_internal_redirect_target(raw_target: str | None) -> str | None:
    target = strip_html(raw_target or "", 500).strip()
    if not target:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target


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


@settings_bp.route("/organization", methods=["GET", "POST"])
@login_required
def organization():
    if current_user.account_type != "organization":
        flash("Organization settings are available for organization accounts only.", "warning")
        return redirect(url_for("settings.account"))

    org_account = OrganizationAccount.query.filter_by(owner_user_id=current_user.id).first()
    next_target = _safe_internal_redirect_target(request.args.get("next") or request.form.get("next"))

    form_data = {
        "org_name": (org_account.org_name if org_account else "").strip(),
        "org_type": (org_account.org_type if org_account else "").strip(),
        "org_domain": (org_account.org_domain if org_account else "").strip(),
        "mission_description": (org_account.mission_description if org_account else "").strip(),
        "logo_url": (org_account.logo_url if org_account and org_account.logo_url else "").strip(),
    }

    if request.method == "POST":
        form_data = {
            "org_name": strip_html(request.form.get("org_name", ""), 300).strip(),
            "org_type": strip_html(request.form.get("org_type", ""), 100).strip(),
            "org_domain": strip_html(request.form.get("org_domain", ""), 200).strip(),
            "mission_description": strip_html(request.form.get("mission_description", ""), 3000).strip(),
            "logo_url": strip_html(request.form.get("logo_url", ""), 500).strip(),
        }

        if not form_data["org_name"] or not form_data["org_type"] or not form_data["org_domain"] or not form_data["mission_description"]:
            flash("Please complete all required organization fields.", "danger")
            return render_template(
                "settings/organization.html",
                org_account=org_account,
                form_data=form_data,
                next_target=next_target,
                org_profile_complete=_is_org_profile_complete(org_account),
            )

        effective_org_tier = (
            current_user.subscription_tier if current_user.subscription_tier in ORG_SUBSCRIPTION_TIERS else "org_starter"
        )

        if not org_account:
            org_account = OrganizationAccount(
                owner_user_id=current_user.id,
                org_name=form_data["org_name"],
                org_type=form_data["org_type"],
                org_domain=form_data["org_domain"],
                mission_description=form_data["mission_description"],
                logo_url=form_data["logo_url"] or None,
                subscription_tier=effective_org_tier,
                monthly_challenge_credits=ORG_DEFAULT_CHALLENGE_CREDITS.get(effective_org_tier, 3),
            )
            db.session.add(org_account)
        else:
            org_account.org_name = form_data["org_name"]
            org_account.org_type = form_data["org_type"]
            org_account.org_domain = form_data["org_domain"]
            org_account.mission_description = form_data["mission_description"]
            org_account.logo_url = form_data["logo_url"] or None

            if org_account.subscription_tier != effective_org_tier:
                org_account.subscription_tier = effective_org_tier

        db.session.commit()
        flash("Organization profile saved.", "success")
        return redirect(next_target or url_for("org.dashboard"))

    return render_template(
        "settings/organization.html",
        org_account=org_account,
        form_data=form_data,
        next_target=next_target,
        org_profile_complete=_is_org_profile_complete(org_account),
    )


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

    if current_user.account_type == "organization" and selected_plan not in ORG_SUBSCRIPTION_TIERS:
        selected_plan = "org_starter"

    plans = service.get_subscription_plans()
    plan_amount_paise = int((plans.get(selected_plan) or {}).get("amount") or 0)
    plan_amount_inr = int(plan_amount_paise / 100) if plan_amount_paise > 0 else 0

    current_user.subscription_tier = selected_plan
    current_user.is_premium = selected_plan != "free"
    current_user.subscription_expires = utcnow() + timedelta(days=30)

    if current_user.account_type == "organization":
        org_account = OrganizationAccount.query.filter_by(owner_user_id=current_user.id).first()
        if org_account:
            org_account.subscription_tier = selected_plan

            upgraded_credits = ORG_DEFAULT_CHALLENGE_CREDITS.get(selected_plan)
            if upgraded_credits and org_account.monthly_challenge_credits < upgraded_credits:
                org_account.monthly_challenge_credits = upgraded_credits

    db.session.add(
        RazorpayPayment(
            user_id=current_user.id,
            plan_name=selected_plan,
            amount_inr=plan_amount_inr,
            amount_paise=plan_amount_paise,
            razorpay_order_id=strip_html(payload.get("razorpay_order_id", ""), 100) or None,
            razorpay_payment_id=strip_html(payload.get("razorpay_payment_id", ""), 100) or None,
            was_verified=True,
            paid_at=utcnow(),
            payment_meta={
                "account_type": current_user.account_type,
                "verification_source": "billing_verify",
                "currency": "INR",
            },
        )
    )

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
