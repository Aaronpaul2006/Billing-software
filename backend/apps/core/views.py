"""Operational endpoints: liveness, readiness, and JSON error pages."""

import logging

import redis
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from .exceptions import PROBLEM_CONTENT_TYPE, problem_body

logger = logging.getLogger(__name__)


# non_atomic_requests: ATOMIC_REQUESTS would otherwise open a database
# transaction (and connection) for these views.
@transaction.non_atomic_requests
@require_GET
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness: the process is up. Touches no dependencies."""
    return JsonResponse({"status": "ok"})


@transaction.non_atomic_requests
@require_GET
def readyz(request: HttpRequest) -> JsonResponse:
    """Readiness: the database and Redis are reachable."""
    checks = {"database": _database_ok(), "redis": _redis_ok()}
    ready = all(checks.values())
    return JsonResponse(
        {
            "status": "ok" if ready else "unavailable",
            "checks": {name: "ok" if ok else "fail" for name, ok in checks.items()},
        },
        status=200 if ready else 503,
    )


def _database_ok() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except DatabaseError:
        logger.warning("readyz: database check failed", exc_info=True)
        return False


def _redis_ok() -> bool:
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1
        )
        with client:
            return bool(client.ping())
    except redis.RedisError:
        logger.warning("readyz: redis check failed", exc_info=True)
        return False


def not_found(request: HttpRequest, exception: Exception) -> JsonResponse:
    body = problem_body(request, status=404, code="not_found", detail="Not found.")
    return JsonResponse(body, status=404, content_type=PROBLEM_CONTENT_TYPE)


def server_error(request: HttpRequest) -> JsonResponse:
    body = problem_body(
        request,
        status=500,
        code="server_error",
        detail="Something went wrong. Quote the request_id when contacting support.",
    )
    return JsonResponse(body, status=500, content_type=PROBLEM_CONTENT_TYPE)
