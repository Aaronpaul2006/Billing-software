import base64

from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

if len(SECRET_KEY) < 50 or "insecure" in SECRET_KEY or "change-me" in SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a random value of at least 50 characters")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production")
if len(JWT_SIGNING_KEY) < 43 or "local-dev" in JWT_SIGNING_KEY:
    raise ImproperlyConfigured("JWT_SIGNING_KEY must be a random value of at least 32 bytes")
_mfa_key = base64.b64decode(MFA_ENCRYPTION_KEY)
if len(_mfa_key) != 32 or b"local-dev" in _mfa_key:
    raise ImproperlyConfigured("MFA_ENCRYPTION_KEY must be 32 random bytes, base64-encoded")
if not CLAMD_HOST:
    raise ImproperlyConfigured("CLAMD_HOST must be set in production: uploads are virus-scanned")

# TLS terminates at the load balancer, which sets X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Behind the reverse proxy (Caddy), which adds the client to X-Forwarded-For.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)

# One JSON object per log line, with the request id (apps/core/logging.py).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.RequestIdFilter"}},
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
# Celery would replace this with its own text format; keep one format everywhere.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# Errors to Sentry when a DSN is configured. No personal data: no request
# bodies (invoices, names), cookies, headers or user IPs leave the server.
SENTRY_DSN: str = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        release=env("RELEASE", default=None),
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
    )

# The API authenticates with bearer tokens, not cookies, so CsrfViewMiddleware
# has nothing to protect. Revisit in Phase 0 step 5: the web refresh-token
# cookie is SameSite=Strict and only accepted by the refresh endpoint.
SILENCED_SYSTEM_CHECKS = ["security.W003"]
