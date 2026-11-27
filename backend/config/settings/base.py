"""Base settings shared by every environment. All secrets come from the environment."""

import base64
import hashlib
from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
env = environ.Env()
environ.Env.read_env(BASE_DIR.parent / ".env")  # repo-root .env for host tools; compose passes env directly

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.common",
    "apps.audit",
    "apps.companies",
    "apps.accounts",
    "apps.rbac",
    "apps.org",
    "apps.notifications",
    "apps.tasks",
    "apps.reviews",
    "apps.timetracking",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.common.middleware.RequestContextMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

# --- Database ---------------------------------------------------------------
# Runtime connects as tasktrack_app (not owner, NOBYPASSRLS). One transaction per
# request so that SET LOCAL tenant settings are scoped to the request.
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", 60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DB_APP_ROLE = env("DB_APP_ROLE", default="tasktrack_app")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
# Email uniqueness is a case-insensitive unique index on lower(email).
SILENCED_SYSTEM_CHECKS = ["auth.W004"]
AUTHENTICATION_BACKENDS = []  # login goes through accounts.services.auth only

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.CharacterClassValidator", "OPTIONS": {"min_classes": 3}},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- File storage -----------------------------------------------------------
# USE_S3=false: files on local disk under MEDIA_ROOT, never exposed by a URL route;
# the API streams them after a permission check. USE_S3=true: private S3 bucket.
USE_S3 = env.bool("USE_S3", False)
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
MEDIA_URL = None
S3_BUCKET = env("S3_BUCKET", default="tasktrack")
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default="")
S3_PUBLIC_ENDPOINT_URL = env("S3_PUBLIC_ENDPOINT_URL", default="")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", default="")
S3_SECRET_KEY = env("S3_SECRET_KEY", default="")
_default_storage = (
    {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": S3_BUCKET,
            "endpoint_url": S3_ENDPOINT_URL or None,
            "access_key": S3_ACCESS_KEY,
            "secret_key": S3_SECRET_KEY,
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 60,
            "file_overwrite": False,
        },
    }
    if USE_S3
    else {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": MEDIA_ROOT}}
)
STORAGES = {
    "default": _default_storage,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Cache, Celery ----------------------------------------------------------
REDIS_URL = env("REDIS_URL")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    # name: (task, schedule)
    "stop-runaway-timers": {"task": "timetracking.stop_runaway_timers", "schedule": crontab(minute="*/15")},
    "dispatch-scheduled-reports": {"task": "reports.dispatch_scheduled_reports", "schedule": crontab(minute="*/15")},
    "send-due-reminders": {"task": "tasks.send_due_reminders", "schedule": crontab(minute=5)},
    "notify-long-blocked": {"task": "tasks.notify_long_blocked", "schedule": crontab(hour=4, minute=0)},
    "purge-expired-exports": {"task": "reports.purge_expired_exports", "schedule": crontab(hour=2, minute=0)},
    "purge-orphan-files": {"task": "tasks.purge_orphan_files", "schedule": crontab(hour=2, minute=30)},
    "purge-old-notifications": {"task": "notifications.purge_old", "schedule": crontab(hour=3, minute=0)},
    "purge-expired-auth-tokens": {"task": "accounts.purge_expired_tokens", "schedule": crontab(hour=3, minute=30)},
    "verify-tenant-integrity": {"task": "common.verify_tenant_integrity", "schedule": crontab(hour=1, minute=0)},
}

# --- Email ------------------------------------------------------------------
MAILERS = {
    "default": {
        "BACKEND": env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"),
        "OPTIONS": {
            "host": env("EMAIL_HOST", default="localhost"),
            "port": env.int("EMAIL_PORT", 1025),
            "username": env("EMAIL_HOST_USER", default=""),
            "password": env("EMAIL_HOST_PASSWORD", default=""),
            "use_tls": env.bool("EMAIL_USE_TLS", False),
            "timeout": 10,
        },
    }
}
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="TaskTrack <no-reply@tasktrack.local>")

# --- Web origin, CORS, CSRF -------------------------------------------------
WEB_ORIGIN = env("WEB_ORIGIN", default="http://localhost:3001")
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[WEB_ORIGIN])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[WEB_ORIGIN])
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it and echoes it in X-CSRFToken
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", True)

# --- Auth tokens ------------------------------------------------------------
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY", default=SECRET_KEY)
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", 10)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", 14)),
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "sub",
    "TOKEN_TYPE_CLAIM": "type",
    "JTI_CLAIM": "jti",
    "UPDATE_LAST_LOGIN": False,
}
REFRESH_COOKIE_NAME = "tt_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth/"
REFRESH_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", True)
IMPERSONATION_MINUTES = 30
INVITE_EXPIRY_HOURS = env.int("INVITE_EXPIRY_HOURS", 48)
PASSWORD_RESET_EXPIRY_MINUTES = env.int("PASSWORD_RESET_EXPIRY_MINUTES", 60)
MFA_TOKEN_SECONDS = 300
LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_BASE_MINUTES = 15
LOGIN_LOCKOUT_MAX_MINUTES = 24 * 60

# Fernet key for encrypting TOTP secrets. Falls back to a key derived from
# SECRET_KEY so development works without extra setup; production sets it.
FIELD_ENCRYPTION_KEY = (
    env("FIELD_ENCRYPTION_KEY", default="")
    or base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()
)

# --- DRF --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    # List views opt in with ``filter_backends = LIST_FILTERS`` (apps.common.views).
    "DEFAULT_FILTER_BACKENDS": [],
    "EXCEPTION_HANDLER": "apps.common.exceptions.exception_handler",
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_RATES": {
        "login": "20/min",
        "login_email": "5/min",
        "mfa": "5/min",
        "password_reset": "3/hour",
        "invite_accept": "10/min",
        "user": "600/min",
    },
}

SPECTACULAR_SETTINGS = {
    "DEFAULT_GENERATOR_CLASS": "apps.common.schema.TenantSafeSchemaGenerator",
    "TITLE": "TaskTrack API",
    "DESCRIPTION": "Multi-tenant task assignment, review and time tracking.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SECURITY": [{"jwtAuth": []}],
    "APPEND_COMPONENTS": {"securitySchemes": {"jwtAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
    "ENUM_NAME_OVERRIDES": {
        "UserStatusEnum": "apps.accounts.models.User.Status",
        "CompanyStatusEnum": "apps.companies.models.Company.Status",
        "InviteStateEnum": ["none", "pending", "expired", "used", "revoked"],
        "TaskStatusEnum": "apps.tasks.models.Status",
        "ProjectStatusEnum": "apps.org.models.Project.Status",
        "LeaveKindEnum": "apps.org.models.LeaveDay.Kind",
        "CommentKindEnum": "apps.tasks.models.TaskComment.Kind",
        "ReviewDecisionEnum": "apps.reviews.models.TaskReview.Decision",
        "TimeEntryStatusEnum": "apps.timetracking.models.TimeEntry.Status",
    },
}
DOCS_PUBLIC = env.bool("DOCS_PUBLIC", True)

# --- Logging, Sentry ----------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processors": "ext://apps.common.logging.FORMATTER_PROCESSORS",
            "foreign_pre_chain": "ext://apps.common.logging.FOREIGN_PRE_CHAIN",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.server": {"level": "WARNING"},
        "django.request": {"level": "ERROR"},
    },
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    from apps.common.logging import sentry_before_send

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="development"),
        send_default_pii=False,
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        before_send=sentry_before_send,
    )

# --- Uploads ----------------------------------------------------------------
ATTACHMENT_MAX_MB = env.int("ATTACHMENT_MAX_MB", 25)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
