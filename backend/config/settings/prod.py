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

# TLS terminates at the load balancer, which sets X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# The API authenticates with bearer tokens, not cookies, so CsrfViewMiddleware
# has nothing to protect. Revisit in Phase 0 step 5: the web refresh-token
# cookie is SameSite=Strict and only accepted by the refresh endpoint.
SILENCED_SYSTEM_CHECKS = ["security.W003"]
