"""Shared view helpers for tenant-scoped endpoints."""

from collections.abc import Callable
from typing import Any, ClassVar

from rest_framework.exceptions import NotAuthenticated
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .errors import PreconditionFailed
from .permissions import HasAction, MfaSatisfied
from .tenancy import Principal
from .versioning import attach_current, expected_version, with_etag


def principal_of(request: Request) -> Principal:
    if not isinstance(request.auth, Principal):  # views using this require authentication
        raise NotAuthenticated
    return request.auth


class ActionAPIView(GenericAPIView):  # type: ignore[type-arg]
    """Permission by action name (docs/01-architecture.md §3): `read_action`
    for GET/HEAD/OPTIONS, `write_action` for everything else. Generic, so list
    endpoints get pagination and filtering from the DRF defaults."""

    read_action: ClassVar[str] = "tenant.read"
    write_action: ClassVar[str]

    def get_permissions(self) -> list[BasePermission]:
        action = self.read_action if self.request.method in SAFE_METHODS else self.write_action
        return [IsAuthenticated(), MfaSatisfied(), HasAction(action)()]

    @property
    def principal(self) -> Principal:
        return principal_of(self.request)


def detail_response(obj: Any, serializer: Any, status: int = 200) -> Response:
    """The serialized object with its ETag (objects carry `version`)."""
    return with_etag(Response(serializer(obj).data, status=status), obj.version)


def list_response(view: GenericAPIView, queryset: Any, serializer: Any) -> Response:  # type: ignore[type-arg]
    page = view.paginate_queryset(view.filter_queryset(queryset))
    return view.get_paginated_response(serializer(page, many=True).data)


def versioned_patch(
    request: Request,
    *,
    load: Callable[[], Any],
    input_serializer: Any,
    update: Callable[[int, dict[str, Any]], Any],
    output_serializer: Any,
    context: dict[str, Any] | None = None,
) -> Response:
    """PATCH flow for editable resources, in the documented order:
    404 (load) → 428/412 If-Match → 422 body → 412 compare-and-set (with the
    current resource in the body) → 200 with the new ETag."""
    obj = load()
    expected = expected_version(request)
    data = input_serializer(
        data=request.data, partial=True, context={"instance": obj, **(context or {})}
    )
    data.is_valid(raise_exception=True)
    try:
        updated = update(expected, data.validated_data)
    except PreconditionFailed as exc:
        attach_current(exc, lambda: output_serializer(load()).data)
        raise
    return detail_response(updated, output_serializer)


def versioned_action(
    request: Request,
    *,
    load: Callable[[], Any],
    run: Callable[[int], Any],
    output_serializer: Any,
) -> Response:
    """State-changing POST on a resource (issue, cancel, ...): 404 → If-Match
    428/412 → run → 412 with the current resource → 200 with the new ETag."""
    load()
    expected = expected_version(request)
    try:
        result = run(expected)
    except PreconditionFailed as exc:
        attach_current(exc, lambda: output_serializer(load()).data)
        raise
    return detail_response(result, output_serializer)
