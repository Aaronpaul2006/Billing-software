import re
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from .models import Role

CLIENTS = ["web", "mobile"]


class _ClientFields(serializers.Serializer[Any]):
    # web: refresh token in an HttpOnly cookie; mobile: in the response body.
    client = serializers.ChoiceField(choices=CLIENTS, default="mobile")
    device_label = serializers.CharField(max_length=100, required=False, allow_blank=True)


class SignupSerializer(_ClientFields):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    full_name = serializers.CharField(min_length=1, max_length=200)
    business_name = serializers.CharField(min_length=1, max_length=200)


class LoginSerializer(_ClientFields):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    tenant_id = serializers.UUIDField(required=False)


class MfaVerifySerializer(_ClientFields):
    mfa_token = serializers.CharField(max_length=2000)
    code = serializers.CharField(max_length=10, required=False)
    recovery_code = serializers.CharField(max_length=20, required=False)
    tenant_id = serializers.UUIDField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get("code")) == bool(attrs.get("recovery_code")):
            raise serializers.ValidationError("Send either code or recovery_code.", code="one_of")
        return attrs


class RefreshSerializer(serializers.Serializer[Any]):
    # Mobile sends the token in the body; web sends nothing (the cookie is used).
    refresh_token = serializers.CharField(max_length=200, required=False)


class SwitchTenantSerializer(_ClientFields):
    tenant_id = serializers.UUIDField()


class MfaEnableSerializer(_ClientFields):
    code = serializers.CharField(max_length=10)


class MfaDisableSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(max_length=10)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


# --- responses (documented in the OpenAPI schema; views build plain dicts) ---------


class TenantSummarySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    legal_name = serializers.CharField()
    role = serializers.CharField()


class TokensSerializer(serializers.Serializer[Any]):
    token_type = serializers.CharField(help_text="Always `Bearer`.")
    access_token = serializers.CharField()
    expires_in = serializers.IntegerField(help_text="Access token lifetime in seconds.")
    session_id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    tenant_id = serializers.UUIDField()
    role = serializers.CharField()
    mfa_enrollment_required = serializers.BooleanField(
        help_text="OWNER/ADMIN without MFA: only enrolment endpoints work until it is on."
    )
    tenants = TenantSummarySerializer(many=True)
    refresh_token = serializers.CharField(
        required=False, help_text="Mobile clients only; web clients get an HttpOnly cookie."
    )
    refresh_expires_at = serializers.DateTimeField(required=False)


class MfaChallengeSerializer(serializers.Serializer[Any]):
    mfa_required = serializers.BooleanField()
    mfa_token = serializers.CharField(help_text="Send to /auth/mfa/verify with a code.")


class MfaEnabledSerializer(TokensSerializer):
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), help_text="Shown once. Each works one time."
    )


class MfaSetupResponseSerializer(serializers.Serializer[Any]):
    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()


class SessionSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    tenant_id = serializers.UUIDField(allow_null=True)
    device_label = serializers.CharField(allow_null=True)
    ip = serializers.CharField(allow_null=True)
    user_agent = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField()
    last_refreshed_at = serializers.DateTimeField()
    current = serializers.BooleanField()


class SessionListSerializer(serializers.Serializer[Any]):
    results = SessionSerializer(many=True)


class MembershipSummarySerializer(serializers.Serializer[Any]):
    tenant_id = serializers.UUIDField()
    legal_name = serializers.CharField()
    role = serializers.CharField()


class VerifyEmailSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(max_length=500)


class PasswordForgotSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)


class PasswordResetSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(max_length=500)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class MeUpdateSerializer(serializers.Serializer[Any]):
    full_name = serializers.CharField(min_length=1, max_length=200, required=False)
    phone = serializers.CharField(max_length=25, required=False, allow_null=True)

    def validate_phone(self, value: str | None) -> str | None:
        """Stored as + and 10-15 digits (the database rule); spaces, dashes and
        brackets people type are dropped."""
        if value is None:
            return None
        digits = re.sub(r"[\s()-]", "", value)
        if not re.fullmatch(r"\+?[0-9]{10,15}", digits):
            raise serializers.ValidationError(
                "A phone number like +91 98470 12345.", code="invalid"
            )
        return digits


class PasswordChangeSerializer(serializers.Serializer[Any]):
    current_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class EmailChangeSerializer(serializers.Serializer[Any]):
    new_email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class MeSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    email_verified = serializers.BooleanField()
    full_name = serializers.CharField()
    phone = serializers.CharField(allow_null=True)
    mfa_enabled = serializers.BooleanField()
    mfa_enrollment_required = serializers.BooleanField()
    tenant_id = serializers.UUIDField()
    role = serializers.CharField()
    memberships = MembershipSummarySerializer(many=True)


class MemberRoleSerializer(serializers.Serializer[Any]):
    role = serializers.ChoiceField(choices=Role.values)


class MemberSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    role = serializers.CharField()
    status = serializers.CharField()
    invited_by = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()


class MemberListSerializer(serializers.Serializer[Any]):
    results = MemberSerializer(many=True)


class InviteSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=Role.values)


class InvitationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    tenant_id = serializers.UUIDField()
    legal_name = serializers.CharField()
    role = serializers.CharField()
    invited_by_name = serializers.CharField(allow_null=True)
    invited_at = serializers.DateTimeField()


class InvitationListSerializer(serializers.Serializer[Any]):
    results = InvitationSerializer(many=True)


# --- invitations by email (K.2) -------------------------------------------------------


class EmailInviteSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=Role.values)


class EmailInvitationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    status = serializers.CharField()
    invited_by = serializers.UUIDField(source="invited_by_id")
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    expired = serializers.SerializerMethodField()

    def get_expired(self, obj: Any) -> bool:
        return bool(obj.expires_at <= timezone.now())


class EmailInvitationListSerializer(serializers.Serializer[Any]):
    results = EmailInvitationSerializer(many=True)


class JoinDetailsSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField()
    legal_name = serializers.CharField()
    role = serializers.CharField()
    invited_by_name = serializers.CharField()
    expires_at = serializers.DateTimeField()


class JoinSerializer(_ClientFields):
    token = serializers.CharField(max_length=500)
    full_name = serializers.CharField(min_length=1, max_length=200)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
