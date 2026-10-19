from .base import *

DEBUG = True
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
REFRESH_COOKIE_SECURE = False  # plain http://127.0.0.1 in development

SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]
