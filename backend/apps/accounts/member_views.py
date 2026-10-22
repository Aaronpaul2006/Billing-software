"""Member management endpoints (docs/02-api-design.md §3). OWNER / ADMIN."""

import uuid
from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import ratelimit
from apps.core.api import principal_of
from apps.core.permissions import HasAction, MfaSatisfied

from . import email_invitations, members
from .serializers import (
    EmailInvitationListSerializer,
    EmailInvitationSerializer,
    EmailInviteSerializer,
    InvitationListSerializer,
    InviteSerializer,
    MemberListSerializer,
    MemberRoleSerializer,
    MemberSerializer,
    TenantSummarySerializer,
)

MANAGE_MEMBERS = (IsAuthenticated, MfaSatisfied, HasAction("members.manage"))


class MemberListView(APIView):
    permission_classes = MANAGE_MEMBERS

    @extend_schema(responses={200: MemberListSerializer}, tags=["members"])
    def get(self, request: Request) -> Response:
        return Response(
            {"results": [asdict(m) for m in members.list_members(principal_of(request))]}
        )

    @extend_schema(request=InviteSerializer, responses={201: MemberSerializer}, tags=["members"])
    def post(self, request: Request) -> Response:
        data = InviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        member = members.invite(
            principal_of(request), data.validated_data["email"], data.validated_data["role"]
        )
        return Response(asdict(member), status=201)


class InvitationListView(APIView):
    """The signed-in user's own pending invitations (any tenant)."""

    permission_classes = (IsAuthenticated,)

    @extend_schema(responses={200: InvitationListSerializer}, tags=["members"])
    def get(self, request: Request) -> Response:
        return Response(
            {"results": [asdict(i) for i in members.my_invitations(principal_of(request))]}
        )


class InvitationAcceptView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(request=None, responses={200: TenantSummarySerializer}, tags=["members"])
    def post(self, request: Request, membership_id: uuid.UUID) -> Response:
        principal = principal_of(request)
        tenant_id = members.respond(principal, membership_id, accept=True)
        joined = next(t for t in members.my_tenants(principal) if t.id == tenant_id)
        return Response(asdict(joined))


class InvitationDeclineView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(request=None, responses={204: None}, tags=["members"])
    def post(self, request: Request, membership_id: uuid.UUID) -> Response:
        members.respond(principal_of(request), membership_id, accept=False)
        return Response(status=204)


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


class EmailInvitationListView(APIView):
    """Invitations to people with no account yet: pending ones, and new ones
    (an email with a link to create the account and join, for 7 days)."""

    permission_classes = MANAGE_MEMBERS

    @extend_schema(responses={200: EmailInvitationListSerializer}, tags=["members"])
    def get(self, request: Request) -> Response:
        rows = email_invitations.pending(principal_of(request))
        return Response({"results": EmailInvitationSerializer(rows, many=True).data})

    @extend_schema(
        request=EmailInviteSerializer, responses={201: EmailInvitationSerializer}, tags=["members"]
    )
    def post(self, request: Request) -> Response:
        principal = principal_of(request)
        ratelimit.enforce(request, "invite_user", str(principal.user_id))
        data = EmailInviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invitation = email_invitations.create(
            principal, data.validated_data["email"], data.validated_data["role"]
        )
        return Response(EmailInvitationSerializer(invitation).data, status=201)


class EmailInvitationDetailView(APIView):
    permission_classes = MANAGE_MEMBERS

    @extend_schema(responses={204: None}, tags=["members"])
    def delete(self, request: Request, invitation_id: uuid.UUID) -> Response:
        email_invitations.revoke(principal_of(request), invitation_id)
        return Response(status=204)


class EmailInvitationResendView(APIView):
    """Send the invitation email again; the link works for 7 more days."""

    permission_classes = MANAGE_MEMBERS

    @extend_schema(request=None, responses={200: EmailInvitationSerializer}, tags=["members"])
    def post(self, request: Request, invitation_id: uuid.UUID) -> Response:
        principal = principal_of(request)
        ratelimit.enforce(request, "invite_user", str(principal.user_id))
        invitation = email_invitations.resend(principal, invitation_id)
        return Response(EmailInvitationSerializer(invitation).data)
