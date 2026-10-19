"""Optimistic locking (docs/02-api-design.md §1).

Editable resources carry `version`; responses send `ETag: "v7"`. Changes
require `If-Match: "v7"`: missing → 428, stale → 412 with the current
resource. The version is bumped with a compare-and-set UPDATE, so two saves
racing from the same version cannot both succeed.
"""

import re
from collections.abc import Callable
from typing import Any

from django.db import models
from django.db.models import F
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response

from .errors import PreconditionFailed, PreconditionRequired

_ETAG = re.compile(r'^(?:W/)?"v(\d+)"$')


def etag(version: int) -> str:
    return f'"v{version}"'


def with_etag(response: Response, version: int) -> Response:
    response["ETag"] = etag(version)
    return response


def expected_version(request: Request) -> int:
    header = request.headers.get("If-Match")
    if not header:
        raise PreconditionRequired(
            'Send If-Match with the ETag you last read, e.g. If-Match: "v3".',
            code="if_match_required",
        )
    match = _ETAG.match(header.strip())
    if match is None:
        raise PreconditionFailed('If-Match must look like "v3".', code="stale_version")
    return int(match.group(1))


def update_versioned(
    queryset: models.QuerySet[Any] | models.Manager[Any],
    pk: Any,
    expected: int,
    current: Callable[[], dict[str, Any]],
    **changes: Any,
) -> int:
    """UPDATE ... WHERE pk = .. AND version = expected; returns the new version.

    `current` builds the up-to-date representation for the 412 body.
    Callers check existence first (404 before 412).
    """
    if "updated_at" not in changes:
        changes["updated_at"] = timezone.now()
    updated = queryset.filter(pk=pk, version=expected).update(version=F("version") + 1, **changes)
    if not updated:
        raise PreconditionFailed(extra={"current": current()})
    return expected + 1
