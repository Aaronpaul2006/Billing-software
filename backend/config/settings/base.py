"""Settings shared by every environment.

Values come from environment variables. For local development they are read
from the repository-root `.env` (the same file docker-compose uses); real
environments inject them from a secrets manager and ship no `.env` file.
"""

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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

# --- Passwords -----------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]

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
    # Secure by default: every endpoint needs an authenticated user unless it
    # opts out explicitly. Authentication classes arrive with JWT (step 5).
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.problem_exception_handler",
    # Money is a string in JSON, never a float.
    "COERCE_DECIMAL_TO_STRING": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Construction Billing API",
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
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
