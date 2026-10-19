from .base import *

ALLOWED_HOSTS = ["testserver", "localhost"]

# Argon2 is deliberately slow; tests hash many passwords. Production hashing is
# asserted separately against base.PASSWORD_HASHERS.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

REFRESH_COOKIE_SECURE = False

SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]
