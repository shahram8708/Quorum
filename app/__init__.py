import logging
import os
from datetime import date

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for
from flask_login import current_user

from app.bootstrap import run_startup_bootstrap
from app.extensions import csrf, db, limiter, login_manager, mail, migrate, scheduler


load_dotenv()

from app.config import config_by_name


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)

    env_name = config_name or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config_by_name.get(env_name, config_by_name["development"]))

    for key in app.config.get("ENV_RENDER_KEYS", []):
        if key in os.environ:
            app.config[key] = os.getenv(key)

    app.config["ENV_RENDERED_VALUES"] = {
        key: app.config.get(key)
        for key in app.config.get("ENV_RENDER_KEYS", [])
    }

    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    if (os.getenv("LOG_LEVEL") or "").upper() == "DEBUG":
        log_level = logging.DEBUG

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)

    logging.getLogger("quorum.ai_service").setLevel(logging.DEBUG)
    logging.getLogger("quorum.routes").setLevel(logging.DEBUG)

    app.logger.info("Quorum app starting up...")

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from app.models import User  # noqa: WPS433

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))

    register_blueprints(app)
    register_error_handlers(app)
    register_context_processors(app)
    register_scheduler_jobs(app)

    from seed_commands import register_seed_commands

    register_seed_commands(app)

    with app.app_context():
        run_startup_bootstrap(app)

    return app


def register_context_processors(app: Flask) -> None:
    from app.models import Notification, OrganizationAccount, Project, ProjectOutcome, ProjectRole
    from app.services.file_handler import generate_presigned_url

    onboarding_allowed_prefixes = ("auth.", "main.", "onboarding.")
    onboarding_allowed_endpoints = {"static"}

    @app.before_request
    def keep_session_alive():
        session.permanent = True

    @app.before_request
    def enforce_onboarding_completion():
        if not current_user.is_authenticated:
            return None
        if current_user.is_admin or not current_user.needs_onboarding:
            return None
        if request.method == "OPTIONS":
            return None

        endpoint = request.endpoint
        if not endpoint:
            return None
        if endpoint in onboarding_allowed_endpoints:
            return None
        if any(endpoint.startswith(prefix) for prefix in onboarding_allowed_prefixes):
            return None

        if request.method == "GET":
            return redirect(url_for("onboarding.index", next=request.path))
        return redirect(url_for("onboarding.index"))

    @app.context_processor
    def global_template_data():
        unread_count = 0
        recent_notifications = []
        created_projects_count = 0
        joined_projects_count = 0
        flagged_projects_count = 0
        pending_outcomes_count = 0
        org_account = None

        if current_user.is_authenticated:
            try:
                unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
                recent_notifications = (
                    Notification.query.filter_by(user_id=current_user.id)
                    .order_by(Notification.created_at.desc())
                    .limit(5)
                    .all()
                )

                created_projects_count = (
                    Project.query.filter_by(creator_user_id=current_user.id, is_published=True)
                    .filter(Project.status.in_(["assembling", "active", "launch_ready", "completed"]))
                    .count()
                )

                joined_projects_count = ProjectRole.query.filter_by(
                    filled_by_user_id=current_user.id,
                    is_filled=True,
                ).count()

                if current_user.account_type == "organization":
                    org_account = OrganizationAccount.query.filter_by(owner_user_id=current_user.id).first()

                if current_user.is_admin:
                    flagged_projects_count = Project.query.filter_by(is_flagged=True).count()
                    pending_outcomes_count = ProjectOutcome.query.filter_by(is_published=False).count()
            except Exception:
                unread_count = 0
                recent_notifications = []
                created_projects_count = 0
                joined_projects_count = 0
                flagged_projects_count = 0
                pending_outcomes_count = 0
                org_account = None

        def resolve_file_url(storage_path: str | None) -> str:
            if not storage_path:
                return ""
            if storage_path.startswith("http://") or storage_path.startswith("https://"):
                return storage_path
            return generate_presigned_url(storage_path)

        return {
            "unread_notifications_count": unread_count,
            "unread_notification_count": unread_count,
            "recent_unread_notifications": recent_notifications,
            "created_projects_count": created_projects_count,
            "joined_projects_count": joined_projects_count,
            "flagged_projects_count": flagged_projects_count,
            "pending_outcomes_count": pending_outcomes_count,
            "org_account": org_account,
            "today": date.today(),
            "env": app.config.get("ENV_RENDERED_VALUES", {}),
            "resolve_file_url": resolve_file_url,
        }


def register_blueprints(app: Flask) -> None:
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.discover import discover_bp
    from app.routes.feed import feed_bp
    from app.routes.main import main_bp
    from app.routes.onboarding import onboarding_bp
    from app.routes.org import org_bp
    from app.routes.outcomes import outcomes_bp
    from app.routes.profile import profile_bp
    from app.routes.projects_create import create_bp
    from app.routes.projects_manage import manage_bp
    from app.routes.projects_public import projects_public_bp
    from app.routes.settings import settings_bp
    from app.routes.tasks import tasks_bp
    from app.routes.templates_bp import templates_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(projects_public_bp)
    app.register_blueprint(create_bp)
    app.register_blueprint(manage_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(outcomes_bp)
    app.register_blueprint(discover_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(org_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(admin_bp)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("errors/500.html"), 500


def register_scheduler_jobs(app: Flask) -> None:
    if app.config.get("TESTING"):
        return

    if scheduler.running:
        return

    from app.services.weekly_digest import run_weekly_digest_for_all_projects
    from app.services.ai_service import refresh_all_civic_pulse

    scheduler.add_job(
        func=lambda: _app_context_runner(app, run_weekly_digest_for_all_projects),
        trigger="cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        id="weekly_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: _app_context_runner(app, refresh_all_civic_pulse),
        trigger="cron",
        hour=6,
        minute=30,
        id="daily_civic_pulse",
        replace_existing=True,
    )
    scheduler.start()


def _app_context_runner(app: Flask, fn):
    with app.app_context():
        fn()
