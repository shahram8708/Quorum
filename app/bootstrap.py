from app.extensions import db
from app.models import User
from seed_commands import seed_projects_data, seed_skills_data


def run_startup_bootstrap(app) -> None:
    if app.config.get("AUTO_CREATE_DB", True):
        db.create_all()

    if app.config.get("AUTO_CREATE_ADMIN_ON_STARTUP", True):
        _ensure_admin_user(app)

    if app.config.get("AUTO_SEED_DATA_ON_STARTUP", True):
        _seed_default_data()


def _ensure_admin_user(app) -> None:
    admin_email = (app.config.get("ADMIN_EMAIL") or "admin@quorum.local").strip().lower()
    admin_password = app.config.get("ADMIN_PASSWORD") or "Admin@12345678"

    admin_user = User.query.filter_by(email=admin_email).first()
    if admin_user:
        admin_user.is_admin = True
        admin_user.account_type = "admin"
        admin_user.is_verified = True
        if not admin_user.username:
            admin_user.username = _next_available_username(app.config.get("ADMIN_USERNAME", "quorum_admin"))
        if not admin_user.password_hash:
            admin_user.set_password(admin_password)
        db.session.commit()
        return

    admin_user = User(
        email=admin_email,
        username=_next_available_username(app.config.get("ADMIN_USERNAME", "quorum_admin")),
        first_name=app.config.get("ADMIN_FIRST_NAME", "Quorum"),
        last_name=app.config.get("ADMIN_LAST_NAME", "Admin"),
        account_type="admin",
        is_admin=True,
        is_verified=True,
        onboarding_complete=True,
        is_premium=True,
        subscription_tier="org_team",
        is_open_to_projects=False,
        city="",
        country="",
    )
    admin_user.set_password(admin_password)
    db.session.add(admin_user)
    db.session.commit()


def _seed_default_data() -> None:
    seed_skills_data()
    seed_projects_data()


def _next_available_username(base_username: str) -> str:
    base = (base_username or "quorum_admin").strip().lower().replace(" ", "_")
    candidate = base
    index = 1

    while User.query.filter_by(username=candidate).first() is not None:
        candidate = f"{base}_{index}"
        index += 1

    return candidate
