"""Auth endpoints (docs/02-api-design.md §2). Thin: validate, call a service, respond."""

import uuid
from dataclasses import asdict
from typing import Any

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import ratelimit
from apps.core.api import principal_of
from apps.core.permissions import MFA_REQUIRED_ROLES
from apps.core.tenancy import Principal, user_context

from . import email_invitations, emails, services
from .models import User
from .serializers import (
    EmailChangeSerializer,
    JoinDetailsSerializer,
    JoinSerializer,
    LoginSerializer,
    MeSerializer,
    MeUpdateSerializer,
    MfaChallengeSerializer,
    MfaDisableSerializer,
    MfaEnabledSerializer,
    MfaEnableSerializer,
    MfaSetupResponseSerializer,
    MfaVerifySerializer,
    PasswordChangeSerializer,
    PasswordForgotSerializer,
    PasswordResetSerializer,
    RefreshSerializer,
    SessionListSerializer,
    SignupSerializer,
    SwitchTenantSerializer,
    TokensSerializer,
    VerifyEmailSerializer,
)
from .services import ClientInfo, MfaChallenge, SessionTokens

ENROLMENT_ALLOWED = [IsAuthenticated]  # reachable before an OWNER/ADMIN has MFA

LOGIN_RESULT = PolymorphicProxySerializer(
    component_name="LoginResult",
    serializers=[TokensSerializer, MfaChallengeSerializer],
    resource_type_field_name=None,
)


def _client(request: Request, data: dict[str, Any] | None = None) -> ClientInfo:
    meta = request.META
    return ClientInfo(
        ip=ratelimit.client_ip(request) or None,
        user_agent=meta.get("HTTP_USER_AGENT") or None,
        device_label=(data or {}).get("device_label") or None,
    )


def _tokens_response(tokens: SessionTokens, client: str, status: int = 200) -> Response:
    body: dict[str, Any] = {
        "token_type": "Bearer",
        "access_token": tokens.access_token,
        "expires_in": int(settings.ACCESS_TOKEN_TTL.total_seconds()),
        "session_id": str(tokens.session_id),
        "user_id": str(tokens.user_id),
        "tenant_id": str(tokens.tenant_id),
        "role": tokens.role,
        "mfa_enrollment_required": tokens.role in MFA_REQUIRED_ROLES and "otp" not in tokens.amr,
        "tenants": [
            {"id": str(t.id), "legal_name": t.legal_name, "role": t.role} for t in tokens.tenants
        ],
    }
    if client == "mobile":
        body["refresh_token"] = tokens.refresh_token
        body["refresh_expires_at"] = tokens.refresh_expires_at
    response = Response(body, status=status)
    if client == "web":
        response.set_cookie(
            settings.REFRESH_COOKIE_NAME,
            tokens.refresh_token,
            expires=tokens.refresh_expires_at,
            path=settings.REFRESH_COOKIE_PATH,
            secure=settings.REFRESH_COOKIE_SECURE,
            httponly=True,
            samesite="Strict",
        )
    response["Cache-Control"] = "no-store"
    return response


class PublicAuthView(APIView):
    """Sign-in endpoints: no access token needed, and any sent is ignored
    (JWTAuthenticationMiddleware checks `ignores_access_token`)."""

    ignores_access_token = True
    authentication_classes = ()
    permission_classes = (AllowAny,)


class SignupView(PublicAuthView):
    @extend_schema(request=SignupSerializer, responses={201: TokensSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "signup_ip", ratelimit.client_ip(request))
        data = SignupSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        tokens = services.signup(
            email=v["email"],
            password=v["password"],
            full_name=v["full_name"],
            business_name=v["business_name"],
            client=_client(request, v),
        )
        return _tokens_response(tokens, v["client"], status=201)


class LoginView(PublicAuthView):
    @extend_schema(request=LoginSerializer, responses={200: LOGIN_RESULT}, tags=["auth"])
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "login_ip", ratelimit.client_ip(request))
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        ratelimit.enforce(request, "login_email", ratelimit.email_key(v["email"]))
        result = services.login(
            email=v["email"],
            password=v["password"],
            tenant_id=v.get("tenant_id"),
            client=_client(request, v),
        )
        if isinstance(result, MfaChallenge):
            return Response(
                {"mfa_required": True, "mfa_token": result.mfa_token, "mfa_method": result.method}
            )
        return _tokens_response(result, v["client"])


class MfaVerifyView(PublicAuthView):
    @extend_schema(request=MfaVerifySerializer, responses={200: TokensSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "mfa_ip", ratelimit.client_ip(request))
        data = MfaVerifySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        tokens = services.verify_mfa_login(
            mfa_token=v["mfa_token"],
            code=v.get("code"),
            recovery_code=v.get("recovery_code"),
            tenant_id=v.get("tenant_id"),
            client=_client(request, v),
        )
        return _tokens_response(tokens, v["client"])


class RefreshView(PublicAuthView):
    @extend_schema(request=RefreshSerializer, responses={200: TokensSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        data = RefreshSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        body_token = data.validated_data.get("refresh_token")
        cookie_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        token = body_token or cookie_token
        if not token:
            raise services.InvalidRefreshToken
        tokens = services.refresh(token, _client(request))
        return _tokens_response(tokens, "mobile" if body_token else "web")


class VerifyEmailView(PublicAuthView):
    @extend_schema(request=VerifyEmailSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        data = VerifyEmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.verify_email(data.validated_data["token"])
        return Response(status=204)


class ResendVerificationView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(request=None, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        principal = principal_of(request)
        ratelimit.enforce(request, "verify_resend_user", str(principal.user_id))
        services.resend_verification(principal)
        return Response(status=204)


class PasswordForgotView(PublicAuthView):
    @extend_schema(request=PasswordForgotSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "password_forgot_ip", ratelimit.client_ip(request))
        data = PasswordForgotSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"]
        ratelimit.enforce(request, "password_forgot_email", ratelimit.email_key(email))
        services.forgot_password(email)
        return Response(status=204)  # the same whether or not the account exists


class PasswordResetView(PublicAuthView):
    @extend_schema(request=PasswordResetSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "password_reset_ip", ratelimit.client_ip(request))
        data = PasswordResetSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.reset_password(v["token"], v["password"])
        return Response(status=204)


class LogoutView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(request=RefreshSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        if isinstance(request.auth, Principal):
            services.logout(request.auth)
        else:
            token = request.data.get("refresh_token") or request.COOKIES.get(
                settings.REFRESH_COOKIE_NAME
            )
            if isinstance(token, str) and token:
                services.logout_refresh_token(token)
        response = Response(status=204)
        response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)
        return response


class SwitchTenantView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(request=SwitchTenantSerializer, responses={200: TokensSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        data = SwitchTenantSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        tokens = services.switch_tenant(principal_of(request), v["tenant_id"], _client(request, v))
        return _tokens_response(tokens, v["client"])


class SessionListView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(responses={200: SessionListSerializer}, tags=["auth"])
    def get(self, request: Request) -> Response:
        return Response(
            {
                "results": [
                    {
                        "id": str(s.id),
                        "tenant_id": str(s.tenant_id) if s.tenant_id else None,
                        "device_label": s.device_label,
                        "ip": s.ip,
                        "user_agent": s.user_agent,
                        "started_at": s.started_at,
                        "last_refreshed_at": s.last_refreshed_at,
                        "current": s.current,
                    }
                    for s in services.list_sessions(principal_of(request))
                ]
            }
        )


class SessionDetailView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(responses={204: None}, tags=["auth"])
    def delete(self, request: Request, session_id: uuid.UUID) -> Response:
        services.revoke_session(principal_of(request), session_id)
        return Response(status=204)


class MfaSetupView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(request=None, responses={200: MfaSetupResponseSerializer}, tags=["mfa"])
    def post(self, request: Request) -> Response:
        setup = services.mfa_setup(principal_of(request))
        response = Response({"secret": setup.secret, "otpauth_uri": setup.otpauth_uri})
        response["Cache-Control"] = "no-store"
        return response


class MfaEnableView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(request=MfaEnableSerializer, responses={200: MfaEnabledSerializer}, tags=["mfa"])
    def post(self, request: Request) -> Response:
        data = MfaEnableSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        codes, tokens = services.mfa_enable(principal_of(request), v["code"], _client(request, v))
        response = _tokens_response(tokens, v["client"])
        response.data["recovery_codes"] = codes  # shown once; stored hashed
        return response


class MfaDisableView(APIView):
    @extend_schema(request=MfaDisableSerializer, responses={204: None}, tags=["mfa"])
    def post(self, request: Request) -> Response:
        data = MfaDisableSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.mfa_disable(
            principal_of(request), data.validated_data["password"], data.validated_data["code"]
        )
        return Response(status=204)


class MeView(APIView):
    permission_classes = ENROLMENT_ALLOWED

    @extend_schema(responses={200: MeSerializer}, tags=["me"])
    def get(self, request: Request) -> Response:
        return _me_response(request)

    @extend_schema(request=MeUpdateSerializer, responses={200: MeSerializer}, tags=["me"])
    def patch(self, request: Request) -> Response:
        data = MeUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.update_profile(principal_of(request), dict(data.validated_data))
        return _me_response(request)


class EmailChangeView(APIView):
    """Ask to change your sign-in email: a link goes to the new address, and the
    email changes only when it is opened."""

    @extend_schema(request=EmailChangeSerializer, responses={204: None}, tags=["me"])
    def post(self, request: Request) -> Response:
        principal = principal_of(request)
        ratelimit.enforce(request, "email_change_user", str(principal.user_id))
        data = EmailChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.request_email_change(principal, v["new_email"], v["password"])
        return Response(status=204)


class JoinView(PublicAuthView):
    """An invitation by email: what it is (GET), and joining with it (POST):
    the account is created, joins the company with the invited role and is
    signed in."""

    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        responses={200: JoinDetailsSerializer},
        tags=["auth"],
    )
    def get(self, request: Request) -> Response:
        token = request.query_params.get("token", "")
        if not token:
            raise emails.link_invalid()
        return Response(asdict(email_invitations.details(token)))

    @extend_schema(request=JoinSerializer, responses={201: TokensSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "signup_ip", ratelimit.client_ip(request))
        data = JoinSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        tokens = email_invitations.join(
            v["token"],
            full_name=v["full_name"],
            password=v["password"],
            client=_client(request, v),
        )
        return _tokens_response(tokens, v["client"], status=201)


class EmailConfirmView(PublicAuthView):
    @extend_schema(request=VerifyEmailSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        data = VerifyEmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.confirm_email_change(data.validated_data["token"])
        return Response(status=204)


class PasswordChangeView(APIView):
    """Change your password while signed in; your other devices are signed out."""

    @extend_schema(request=PasswordChangeSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        principal = principal_of(request)
        ratelimit.enforce(request, "password_change_user", str(principal.user_id))
        data = PasswordChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.change_password(principal, v["current_password"], v["new_password"])
        return Response(status=204)


def _me_response(request: Request) -> Response:
    """The signed-in user and their companies (GET and PATCH /me)."""
    principal = principal_of(request)
    user = User.objects.get(pk=principal.user_id)
    with user_context(principal.user_id):
        memberships = services.active_memberships(principal.user_id)
    return Response(
        {
            "id": str(user.pk),
            "email": user.email,
            "email_verified": user.email_verified_at is not None,
            "full_name": user.full_name,
            "phone": user.phone,
            "mfa_enabled": user.mfa_enabled,
            "mfa_enrollment_required": principal.role in MFA_REQUIRED_ROLES
            and "otp" not in principal.amr,
            "tenant_id": str(principal.tenant_id),
            "role": principal.role,
            "memberships": [
                {"tenant_id": str(t.id), "legal_name": t.legal_name, "role": m.role}
                for m, t in memberships
            ],
        }
    )
