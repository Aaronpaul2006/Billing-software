"""Member management endpoints (docs/02-api-design.md §3). OWNER / ADMIN."""

import uuid
from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasAction, MfaSatisfied

from . import members
from .serializers import MemberListSerializer, MemberRoleSerializer, MemberSerializer
from .views import principal_of

MANAGE_MEMBERS = (IsAuthenticated, MfaSatisfied, HasAction("members.manage"))


class MemberListView(APIView):
    permission_classes = MANAGE_MEMBERS

    @extend_schema(responses={200: MemberListSerializer}, tags=["members"])
    def get(self, request: Request) -> Response:
        return Response(
            {"results": [asdict(m) for m in members.list_members(principal_of(request))]}
        )


class MemberDetailView(APIView):
    permission_classes = MANAGE_MEMBERS

    @extend_schema(
        request=MemberRoleSerializer, responses={200: MemberSerializer}, tags=["members"]
    )
    def patch(self, request: Request, membership_id: uuid.UUID) -> Response:
        data = MemberRoleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        member = members.change_role(
            principal_of(request), membership_id, data.validated_data["role"]
        )
        return Response(asdict(member))

    @extend_schema(responses={204: None}, tags=["members"])
    def delete(self, request: Request, membership_id: uuid.UUID) -> Response:
        members.revoke(principal_of(request), membership_id)
        return Response(status=204)
