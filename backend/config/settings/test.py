from .base import *

ALLOWED_HOSTS = ["testserver", "localhost"]

# Argon2 is deliberately slow; tests hash many passwords. Production hashing is
# asserted separately against base.PASSWORD_HASHERS.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

REFRESH_COOKIE_SECURE = False
RENDER_PDF_ON_ISSUE = False  # tests render explicitly
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"  # mail.outbox
CELERY_TASK_ALWAYS_EAGER = True
APP_BASE_URL = "https://app.example.test"

SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]
