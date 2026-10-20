"""Rate limits: fixed-window counters in Redis (docs/01-architecture.md §6).

A counter starts with the first request and lives for its rule's window. One
Lua script increments it and sets the expiry, so concurrent requests are
counted exactly. Sign-in style views call `enforce()` with their own rules;
RateLimitMiddleware limits every signed-in request per user and writes the
RateLimit-* headers for whichever rule the request came closest to.

If Redis cannot be reached the request is allowed and a warning is logged: an
outage must not lock every user out, and the database lockout still guards
passwords.
"""

import hashlib
import ipaddress
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any

import redis
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from .errors import DomainError
from .exceptions import PROBLEM_CONTENT_TYPE, problem_body

log = logging.getLogger(__name__)

_HIT = """
local n = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {n, ttl}
"""


@dataclass(frozen=True)
class Usage:
    limit: int
    count: int
    reset: int  # seconds until the window ends

    @property
    def remaining(self) -> int:
        return max(self.limit - self.count, 0)

    @property
    def exceeded(self) -> bool:
        return self.count > self.limit


class RateLimited(DomainError):
    status = 429
    code = "rate_limited"
    detail = "Too many requests. Try again later."


@cache
def _script() -> Any:
    client = redis.Redis.from_url(
        settings.REDIS_URL, socket_timeout=0.25, socket_connect_timeout=0.25
    )
    return client.register_script(_HIT)


def hit(rule: str, key: str) -> Usage | None:
    """Count one request against `rule` for `key`; None if limits are off or Redis is down."""
    if not settings.RATE_LIMIT_ENABLED:
        return None
    limit, window = settings.RATE_LIMITS[rule]
    try:
        count, ttl = _script()(keys=[f"{settings.RATE_LIMIT_PREFIX}{rule}:{key}"], args=[window])
    except redis.RedisError as exc:
        log.warning("rate limit %s not checked, Redis unreachable: %s", rule, exc)
        return None
    return Usage(limit=limit, count=int(count), reset=max(int(ttl), 1))


def _remember(request: Any, usage: Usage) -> None:
    """Keep the usage the response headers should report: an exceeded rule
    first (the longest wait), otherwise the one with the fewest requests left."""
    http_request = getattr(request, "_request", request)  # a DRF Request wraps it
    current: Usage | None = getattr(http_request, "rate_limit", None)

    def rank(u: Usage) -> tuple[bool, int, int]:
        return (u.exceeded, u.reset if u.exceeded else -u.remaining, u.reset)

    if current is None or rank(usage) > rank(current):
        http_request.rate_limit = usage


def _wait(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = -(-seconds // 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def too_many(usage: Usage) -> RateLimited:
    return RateLimited(
        f"Too many attempts. Try again in {_wait(usage.reset)}.",
        extra={"retry_after": usage.reset},
    )


def enforce(request: Any, rule: str, key: str) -> None:
    """Count this request; raise 429 rate_limited once `key` is over the limit."""
    usage = hit(rule, key)
    if usage is None:
        return
    _remember(request, usage)
    if usage.exceeded:
        raise too_many(usage)


def email_key(email: str) -> str:
    """Emails are not stored in Redis in the clear."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def client_ip(request: Any) -> str:
    """The caller's address. Behind TRUSTED_PROXY_COUNT proxies, the entry the
    outermost trusted proxy added to X-Forwarded-For; entries further left
    are whatever the client sent and are ignored."""
    meta = getattr(request, "META", {})
    remote = str(meta.get("REMOTE_ADDR") or "")
    hops = settings.TRUSTED_PROXY_COUNT
    if hops <= 0:
        return remote
    forwarded = [p.strip() for p in str(meta.get("HTTP_X_FORWARDED_FOR", "")).split(",")]
    chain = [p for p in forwarded if p] + [remote]
    candidate = chain[-(hops + 1)] if len(chain) > hops else chain[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return remote


class RateLimitMiddleware:
    """Limits every signed-in request per user (after JWTAuthenticationMiddleware,
    before a tenant transaction is opened) and adds the RateLimit-* headers."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        principal = getattr(request, "principal", None)
        usage = hit("api_user", str(principal.user_id)) if principal is not None else None
        if usage is not None:
            _remember(request, usage)
        if usage is not None and usage.exceeded:
            response: HttpResponse = _problem(request, too_many(usage))
        else:
            response = self.get_response(request)
        current: Usage | None = getattr(request, "rate_limit", None)
        if current is not None:
            response["RateLimit-Limit"] = str(current.limit)
            response["RateLimit-Remaining"] = str(current.remaining)
            response["RateLimit-Reset"] = str(current.reset)
            if response.status_code == 429:
                response["Retry-After"] = str(current.reset)
        return response


def _problem(request: HttpRequest, exc: RateLimited) -> JsonResponse:
    body = problem_body(request, status=exc.status, code=exc.code, detail=exc.detail)
    body.update(exc.extra)
    return JsonResponse(body, status=exc.status, content_type=PROBLEM_CONTENT_TYPE)
