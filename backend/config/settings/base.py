"""Settings shared by every environment.

Values come from environment variables. For local development they are read
from the repository-root `.env` (the same file docker-compose uses); real
environments inject them from a secrets manager and ship no `.env` file.
"""

from datetime import timedelta
from pathlib import Path

import environ

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

env = environ.Env()
if (REPO_ROOT / ".env").is_file():
    # Never overrides variables already set in the process environment.
    environ.Env.read_env(REPO_ROOT / ".env")

SECRET_KEY: str = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# contrib.auth / admin are not installed: users live in the `users` table
# (apps.accounts) and authentication is JWT (Phase 0 step 5).
INSTALLED_APPS = [
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.core",
    "apps.audit",
    "apps.tenants",
    "apps.accounts",
    "apps.parties",
    "apps.projects",
    "apps.catalog",
    "apps.files",
    "apps.documents",
    "apps.payments",
    "apps.expenses",
    "apps.reports",
    "apps.tds",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Verifies the access token and sets request.principal ...
    "apps.accounts.middleware.JWTAuthenticationMiddleware",
    # ... which this one turns into the request's tenant context.
    "apps.core.middleware.TenantContextMiddleware",
]

# API paths have no trailing slash; never redirect (it would drop POST bodies).
APPEND_SLASH = False

ROOT_URLCONF = "config.urls"

# Used by the OpenAPI docs page, DRF's browsable API (dev) and, later, PDF
# templates. Autoescaping stays on (Django default).
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

STATIC_URL = "static/"
STATIC_ROOT = BACKEND_DIR / "staticfiles"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ------------------------------------------------------------------
# Two connections to the same database (docs/01-architecture.md §2.4):
#   default  billing_app login: every query, always subject to RLS.
#   owner    billing_owner: migrations only (manage.py migrate --database=owner).
# ATOMIC_REQUESTS: every request is one transaction, which is what makes the
# transaction-local tenant context (set_config(..., true)) safe with pooling.
# In tests `default` mirrors `owner`: the owner creates and migrates the test
# database, and tests then run against it as the app role.
DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "ATOMIC_REQUESTS": True,
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},  # fail fast instead of hanging
        "TEST": {"MIRROR": "owner"},
    },
    "owner": {
        **env.db("DATABASE_OWNER_URL"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 5},
    },
}
DATABASE_ROUTERS = ["apps.core.db_router.MigrationsAsOwnerRouter"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL: str = env("REDIS_URL")

# --- Background work (Celery) ------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
RENDER_PDF_ON_ISSUE = True

# --- Object storage (S3 API) -------------------------------------------------------
S3_ENDPOINT_URL: str | None = env("S3_ENDPOINT_URL", default=None)  # None: AWS S3
S3_PUBLIC_ENDPOINT_URL: str | None = env("S3_PUBLIC_ENDPOINT_URL", default=None)
S3_REGION: str = env("S3_REGION", default="ap-south-1")
S3_BUCKET: str = env("S3_BUCKET")
S3_ACCESS_KEY: str = env("S3_ACCESS_KEY")
S3_SECRET_KEY: str = env("S3_SECRET_KEY")

# --- Passwords -----------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]
_validators = "django.contrib.auth.password_validation"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": f"{_validators}.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("email", "full_name")},
    },
    {"NAME": f"{_validators}.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": f"{_validators}.CommonPasswordValidator"},  # ~20k breached/common passwords
    {"NAME": f"{_validators}.NumericPasswordValidator"},
]

# --- Authentication (docs/01-architecture.md §6) -------------------------------
# Access tokens: JWT, HS256, short-lived. The key id goes in the JWT header so
# the key can be rotated later without invalidating every session at once.
JWT_SIGNING_KEY: str = env("JWT_SIGNING_KEY")
JWT_KEY_ID: str = env("JWT_KEY_ID", default="k1")
JWT_ISSUER: str = env("JWT_ISSUER", default="billing-api")
ACCESS_TOKEN_TTL = timedelta(minutes=10)
MFA_CHALLENGE_TTL = timedelta(minutes=5)
# Refresh tokens: opaque, stored as SHA-256, rotated on every use.
REFRESH_TOKEN_TTL = timedelta(days=30)
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
REFRESH_COOKIE_SECURE = True
# Account lockout after repeated failures: 1, 2, 4 ... minutes, capped.
LOGIN_LOCKOUT_THRESHOLD = 5
LOGIN_LOCKOUT_MAX = timedelta(hours=1)
# AES-256-GCM key (base64, 32 bytes) for TOTP secrets. Production: from a KMS.
MFA_ENCRYPTION_KEY: str = env("MFA_ENCRYPTION_KEY")
MFA_ISSUER_NAME = "Construction Billing"

# --- Internationalisation ------------------------------------------------------
LANGUAGE_CODE = "en-in"
TIME_ZONE = "UTC"  # stored and served in UTC; display timezone is a tenant setting
USE_I18N = False
USE_TZ = True

# --- Security headers ----------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- REST framework ------------------------------------------------------------
REST_FRAMEWORK = {
    # Secure by default: every endpoint needs an authenticated user, and
    # OWNER/ADMIN must have passed MFA, unless a view opts out explicitly.
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.PrincipalAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.core.permissions.MfaSatisfied",
    ],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.problem_exception_handler",
    # Money is a string in JSON, never a float.
    "COERCE_DECIMAL_TO_STRING": True,
    # docs/02-api-design.md §1: cursor pagination, exact filters, allow-listed ordering
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.CursorPage",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "ORDERING_PARAM": "ordering",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Construction Billing API",
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    # one named enum for the GST state codes used by several resources
    "ENUM_NAME_OVERRIDES": {
        "StateCodeEnum": "apps.core.serializers.STATE_CHOICES",
        "DocTypeEnum": "apps.tenants.models.DocType",
        "DraftableDocTypeEnum": "apps.documents.services.drafts.DRAFTABLE_TYPES",
        "DocumentStatusEnum": "apps.documents.models.DocumentStatus",
        "ProjectStatusEnum": "apps.projects.models.ProjectStatus",
        "TenantStatusEnum": "apps.tenants.models.TenantStatus",
        "MembershipStatusEnum": "apps.accounts.models.MembershipStatus",
        # payments and expenses share RECORDED / VOIDED
        "RecordStatusEnum": "apps.payments.models.PaymentStatus",
        "PaymentModeEnum": "apps.payments.models.PaymentMode",
        "RetentionReleaseStatusEnum": "apps.payments.models.RetentionReleaseStatus",
        "RetentionBookEnum": "apps.payments.models.RetentionBook",
    },
    # The schema is public only in dev (see dev.py).
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}

# --- Logging -------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
