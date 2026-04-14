import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_database_uri(uri: str | None, fallback: str) -> str:
    value = (uri or "").strip()
    if not value:
        return fallback
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://") :]
    return value


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = "sqlite:///quorum_dev.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 25))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "noreply@quorum.org")

    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
    AWS_S3_REGION = os.getenv("AWS_S3_REGION", "ap-south-1")
    USE_S3 = _as_bool(os.getenv("USE_S3"), default=False)
    LOCAL_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH", str(BASE_DIR / "local_storage"))

    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    RAZORPAY_CREATOR_PRO_AMOUNT = int(os.getenv("RAZORPAY_CREATOR_PRO_AMOUNT", 74900))
    RAZORPAY_ORG_STARTER_AMOUNT = int(os.getenv("RAZORPAY_ORG_STARTER_AMOUNT", 499900))
    RAZORPAY_ORG_TEAM_AMOUNT = int(os.getenv("RAZORPAY_ORG_TEAM_AMOUNT", 1499900))

    BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")

    FREE_TIER_MAX_ACTIVE_PROJECTS = int(os.getenv("FREE_TIER_MAX_ACTIVE_PROJECTS", 2))
    FREE_TIER_MAX_TEAM_SIZE = int(os.getenv("FREE_TIER_MAX_TEAM_SIZE", 8))
    FREE_TIER_MAX_TIMELINE_DAYS = int(os.getenv("FREE_TIER_MAX_TIMELINE_DAYS", 60))

    DIGEST_EMAIL_DAY = int(os.getenv("DIGEST_EMAIL_DAY", 1))
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 10))

    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
    SENTRY_DSN = os.getenv("SENTRY_DSN")

    AUTO_CREATE_DB = _as_bool(os.getenv("AUTO_CREATE_DB"), default=True)
    AUTO_CREATE_ADMIN_ON_STARTUP = _as_bool(os.getenv("AUTO_CREATE_ADMIN_ON_STARTUP"), default=True)
    AUTO_SEED_DATA_ON_STARTUP = _as_bool(os.getenv("AUTO_SEED_DATA_ON_STARTUP"), default=True)

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@quorum.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@12345678")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "quorum_admin")
    ADMIN_FIRST_NAME = os.getenv("ADMIN_FIRST_NAME", "Quorum")
    ADMIN_LAST_NAME = os.getenv("ADMIN_LAST_NAME", "Admin")

    ENV_RENDER_KEYS = [
        "FLASK_ENV",
        "FLASK_DEBUG",
        "BASE_URL",
        "DATABASE_URL",
        "DEV_DATABASE_URL",
        "USE_S3",
        "AWS_S3_BUCKET",
        "AWS_S3_REGION",
        "RAZORPAY_KEY_ID",
    ]

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=4)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = _normalize_database_uri(
        os.getenv("DEV_DATABASE_URL") or os.getenv("DATABASE_URL_DEV"),
        "sqlite:///quorum_dev.db",
    )
    USE_S3 = _as_bool(os.getenv("USE_S3"), default=False)


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    AUTO_CREATE_ADMIN_ON_STARTUP = False
    AUTO_SEED_DATA_ON_STARTUP = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SQLALCHEMY_DATABASE_URI = _normalize_database_uri(
        os.getenv("DATABASE_URL"),
        "postgresql://quorum_user:password@localhost/quorum_prod",
    )
    USE_S3 = _as_bool(os.getenv("USE_S3"), default=True)


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
