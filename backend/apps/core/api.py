"""Shared view helpers for tenant-scoped endpoints."""

from typing import ClassVar

from rest_framework.exceptions import NotAuthenticated
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request

from .permissions import HasAction, MfaSatisfied
from .tenancy import Principal


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
