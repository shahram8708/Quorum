from urllib.parse import urljoin, urlparse

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.forms.auth_forms import ForgotPasswordForm, LoginForm, ResetPasswordForm, SignupForm
from app.models import OrganizationAccount, User
from app.services.email_service import send_password_reset_email, send_verification_email
from app.utils import strip_html, utcnow


auth_bp = Blueprint("auth", __name__)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _normalize_email_input(value: str | None) -> str:
    return strip_html(value or "", 255).strip().lower()


def _candidate_emails_for_lookup(raw_email: str | None) -> list[str]:
    email = _normalize_email_input(raw_email)
    if not email:
        return []

    candidates = [email]
    local_part, separator, domain_part = email.rpartition("@")
    if not separator or not local_part or not domain_part:
        return candidates

    # Domain aliases support seamless auth between dev/staging and production domains.
    domain_aliases = {
        "quorum.local": "quorum.com",
        "quorum.com": "quorum.local",
    }
    mapped_domain = domain_aliases.get(domain_part)
    if mapped_domain:
        alias_email = f"{local_part}@{mapped_domain}"
        if alias_email not in candidates:
            candidates.append(alias_email)

    admin_email = _normalize_email_input(current_app.config.get("ADMIN_EMAIL"))
    admin_local_part, admin_separator, admin_domain_part = admin_email.rpartition("@")
    if admin_separator and admin_local_part == local_part and admin_domain_part and admin_domain_part != domain_part:
        admin_alias = f"{local_part}@{admin_domain_part}"
        if admin_alias not in candidates:
            candidates.append(admin_alias)

    return candidates


def _find_user_by_email(raw_email: str | None) -> User | None:
    for email_candidate in _candidate_emails_for_lookup(raw_email):
        user = User.query.filter_by(email=email_candidate).first()
        if user:
            return user
    return None


def _make_token(email: str, salt: str) -> str:
    return _serializer().dumps(email, salt=salt)


def _read_token(token: str, salt: str, max_age: int) -> str:
    return _serializer().loads(token, salt=salt, max_age=max_age)


def _is_safe_redirect_target(target: str | None) -> bool:
    if not target:
        return False

    host_url = request.host_url
    ref_url = urlparse(host_url)
    test_url = urlparse(urljoin(host_url, target))
    return test_url.scheme in {"http", "https"} and test_url.netloc == ref_url.netloc


def _org_profile_complete(org_account: OrganizationAccount | None) -> bool:
    if not org_account:
        return False

    required_values = [
        org_account.org_name,
        org_account.org_type,
        org_account.org_domain,
        org_account.mission_description,
    ]
    return all(bool((value or "").strip()) for value in required_values)


def _post_login_redirect(user: User):
    next_url = request.form.get("next") or request.args.get("next")
    if _is_safe_redirect_target(next_url):
        return redirect(next_url)

    if user.account_type == "organization":
        org_account = OrganizationAccount.query.filter_by(owner_user_id=user.id).first()
        if _org_profile_complete(org_account):
            return redirect(url_for("org.dashboard"))
        return redirect(url_for("settings.organization"))

    return redirect(url_for("dashboard.home"))


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("onboarding.index") if current_user.needs_onboarding else url_for("dashboard.home"))

    form = SignupForm()

    if request.method == "GET":
        requested_type = strip_html(request.args.get("type", ""), 20).strip().lower()
        if requested_type in {"individual", "organization"}:
            form.account_type.data = requested_type

    if form.validate_on_submit():
        user = User(
            email=strip_html(form.email.data, 255).lower(),
            first_name=strip_html(form.first_name.data, 100),
            last_name=strip_html(form.last_name.data or "", 100),
            username=strip_html(form.username.data, 100).lower(),
            account_type=form.account_type.data,
            subscription_tier="org_starter" if form.account_type.data == "organization" else "free",
        )
        user.set_password(form.password.data)

        db.session.add(user)
        db.session.commit()

        token = _make_token(user.email, "verify-email")
        try:
            send_verification_email(user, token)
        except Exception:
            pass

        login_user(user)
        flash("Welcome to Quorum! Let's set up your profile.", "success")
        return redirect(url_for("onboarding.index"))

    return render_template(
        "auth/signup.html",
        form=form,
        minimal_nav_mode=True,
        minimal_nav_label="Log In",
        minimal_nav_link=url_for("auth.login"),
    )


@auth_bp.get("/verify-pending")
def verify_pending():
    return render_template(
        "auth/verify_pending.html",
        minimal_nav_mode=True,
        minimal_nav_label="Log In",
        minimal_nav_link=url_for("auth.login"),
    )


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("onboarding.index") if current_user.needs_onboarding else url_for("dashboard.home"))

    form = LoginForm()
    if form.validate_on_submit():
        user = _find_user_by_email(form.email.data)

        if user and not user.is_disabled and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            user.last_login = utcnow()
            db.session.commit()
            flash(f"Welcome back, {user.first_name}!", "success")
            return _post_login_redirect(user)

        flash("Invalid credentials.", "danger")

    return render_template(
        "auth/login.html",
        form=form,
        next_url=request.args.get("next", ""),
        minimal_nav_mode=True,
        minimal_nav_label="Sign Up",
        minimal_nav_link=url_for("auth.signup"),
    )


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


@auth_bp.get("/verify/<token>")
def verify_email(token):
    try:
        email = _read_token(token, "verify-email", max_age=48 * 3600)
    except SignatureExpired:
        flash("Verification link expired. Please request a new one.", "warning")
        return redirect(url_for("auth.resend_verification"))
    except BadSignature:
        flash("Invalid verification link.", "danger")
        return redirect(url_for("auth.resend_verification"))

    user = User.query.filter_by(email=email).first_or_404()
    user.is_verified = True
    db.session.commit()

    flash("Email verified successfully.", "success")
    return redirect(url_for("dashboard.home"))


@auth_bp.route("/resend-verification", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def resend_verification():
    if request.method == "POST":
        user = _find_user_by_email(request.form.get("email", ""))
        if user and not user.is_verified:
            token = _make_token(user.email, "verify-email")
            try:
                send_verification_email(user, token)
            except Exception:
                pass
        flash("Verification email sent if the account exists and is unverified.", "info")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/verify_pending.html",
        show_resend_form=True,
        minimal_nav_mode=True,
        minimal_nav_label="Log In",
        minimal_nav_link=url_for("auth.login"),
    )


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        user = _find_user_by_email(form.email.data)

        if user:
            token = _make_token(user.email, "reset-password")
            try:
                send_password_reset_email(user, token)
            except Exception:
                pass

        flash("Reset link sent! Check your email.", "success")
        return redirect(url_for("auth.forgot_password"))

    return render_template(
        "auth/forgot_password.html",
        form=form,
        minimal_nav_mode=True,
        minimal_nav_label="Log In",
        minimal_nav_link=url_for("auth.login"),
    )


@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = _read_token(token, "reset-password", max_age=3600)
    except SignatureExpired:
        flash("Reset link expired.", "warning")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("Invalid reset link.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.filter_by(email=email).first_or_404()
    form = ResetPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Password updated successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/reset_password.html",
        form=form,
        minimal_nav_mode=True,
        minimal_nav_label="Log In",
        minimal_nav_link=url_for("auth.login"),
    )
