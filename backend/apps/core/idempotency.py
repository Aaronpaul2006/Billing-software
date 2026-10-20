"""Idempotency keys for money-moving POSTs (docs/02-api-design.md §1).

    class PaymentListView(APIView):
        @idempotent
        def post(self, request): ...

The client sends `Idempotency-Key: <uuid>`, generated once per user action
and reused on retries:

* same key + same request  → the stored response is replayed
  (header `Idempotent-Replayed: true`), nothing runs twice;
* same key + other request → 422 idempotency_key_reused;
* no key                   → 428 idempotency_key_required.

The key row is written in the request's own transaction, so it commits
together with the effect, or not at all: a failed request leaves no key
behind and the retry runs again. A concurrent duplicate waits on the
unique index (tenant, user, key) until the first commits, then replays.
Keys expire after 24 hours.
"""

import hashlib
import json
from collections.abc import Callable
from functools import wraps
from typing import Any, cast

from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.http import QueryDict
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.encoders import JSONEncoder

from .errors import Conflict, Invalid, PreconditionRequired, Unauthenticated
from .models import IdempotencyKey, IdempotencyKeyState
from .tenancy import Principal

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"

Handler = Callable[..., Response]


def _file_digest(upload: UploadedFile) -> str:
    h = hashlib.sha256()
    for chunk in upload.chunks():
        h.update(chunk)
    upload.seek(0)
    return f"sha256:{h.hexdigest()}"


def _canonical(data: Any) -> Any:
    """JSON bodies as they are; multipart forms with each file as its digest."""
    if isinstance(data, QueryDict):
        return {
            key: [_file_digest(v) if isinstance(v, UploadedFile) else v for v in values]
            for key, values in data.lists()
        }
    return data


def _request_hash(request: Request) -> bytes:
    body = json.dumps(
        _canonical(request.data), sort_keys=True, separators=(",", ":"), cls=JSONEncoder
    )
    raw = f"{request.method}\n{request.path}\n{body}".encode()
    return hashlib.sha256(raw).digest()


def _claim(principal: Principal, key: str, request: Request, digest: bytes) -> IdempotencyKey:
    """Insert the key (IN_PROGRESS) or return the existing row for it."""
    for _ in range(2):
        try:
            with transaction.atomic():
                return cast(
                    IdempotencyKey,
                    IdempotencyKey.objects.create(
                        user_id=principal.user_id,
                        key=key,
                        request_method=request.method,
                        request_path=request.path,
                        request_hash=digest,
                    ),
                )
        except IntegrityError:
            existing = cast(
                IdempotencyKey, IdempotencyKey.objects.get(user_id=principal.user_id, key=key)
            )
            if existing.expires_at > timezone.now():
                return existing
            existing.delete()  # expired: the key may be used afresh
    raise Conflict("Retry the request.", code="idempotency_key_in_use")


def idempotent(handler: Handler) -> Handler:
    @wraps(handler)
    def wrapper(view: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
        principal = request.auth
        if not isinstance(principal, Principal):
            raise Unauthenticated
        key = request.headers.get(HEADER, "").strip()
        if not key:
            raise PreconditionRequired(
                f"Send an {HEADER} header (a new UUID per action, reused on retries).",
                code="idempotency_key_required",
            )
        if not 16 <= len(key) <= 100:
            raise Invalid(HEADER, "Use a UUID (16 to 100 characters).", code="invalid_key")

        digest = _request_hash(request)
        row = _claim(principal, key, request, digest)
        if row.state == IdempotencyKeyState.COMPLETED:
            if bytes(row.request_hash) != digest:
                raise Invalid(
                    HEADER,
                    "This key was already used for a different request.",
                    code="idempotency_key_reused",
                )
            replay = Response(row.response_body, status=row.response_status)
            replay[REPLAYED_HEADER] = "true"
            return replay
        if row.request_hash is not None and bytes(row.request_hash) != digest:
            # IN_PROGRESS rows are never visible to other transactions (they
            # commit as COMPLETED); seeing one with another hash is a reuse.
            raise Invalid(HEADER, "This key is in use.", code="idempotency_key_reused")

        response = handler(view, request, *args, **kwargs)
        # Errors raise and roll back (key included). Store what was returned.
        row.state = IdempotencyKeyState.COMPLETED
        row.response_status = response.status_code
        row.response_body = json.loads(json.dumps(response.data, cls=JSONEncoder))
        row.save(update_fields=["state", "response_status", "response_body"])
        return response

    return wrapper
