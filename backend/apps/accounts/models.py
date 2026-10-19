from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.db import (
    CITextField,
    SQLDefault,
    created_at,
    length_between,
    one_of,
    ref,
    regex,
    tenant_ref,
    updated_at,
    uuid7_pk,
)


class Role(models.TextChoices):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    ACCOUNTANT = "ACCOUNTANT"
    SITE_ENGINEER = "SITE_ENGINEER"
    VIEWER = "VIEWER"


class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


class User(models.Model):
    """A global identity; memberships attach it to tenants."""

    Status = UserStatus
    id = uuid7_pk()
    email = CITextField()
    password_hash = models.TextField()  # argon2id encoded string
    full_name = models.TextField()
    phone = models.TextField(null=True)  # noqa: DJ001 - mirrors schema (NULL = not given)
    mfa_enabled = models.BooleanField(default=False, db_default=False)
    mfa_secret_enc = models.BinaryField(null=True)  # TOTP secret, envelope-encrypted
    # SHA-256 (hex) of the unused one-time recovery codes.
    mfa_recovery_codes = ArrayField(
        models.TextField(),
        default=list,
        db_default=SQLDefault("'{}'::text[]", ArrayField(models.TextField())),
    )
    mfa_last_used_step = models.BigIntegerField(null=True)  # TOTP replay protection
    status = models.TextField(
        choices=Status, default=UserStatus.ACTIVE, db_default=UserStatus.ACTIVE
    )
    failed_login_count = models.IntegerField(default=0, db_default=0)
    locked_until = models.DateTimeField(null=True)
    last_login_at = models.DateTimeField(null=True)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(fields=["email"], name="users_email_key"),
            length_between("full_name", 1, 200, "users_full_name_check"),
            regex("phone", r"^\+?[0-9]{10,15}$", "users_phone_check"),
            one_of("status", UserStatus.values, "users_status_check"),
            models.CheckConstraint(
                condition=Q(failed_login_count__gte=0), name="users_failed_login_count_check"
            ),
            models.CheckConstraint(
                condition=Q(mfa_enabled=False) | Q(mfa_secret_enc__isnull=False),
                name="users_mfa_secret_check",
            ),
        ]

    def __str__(self) -> str:
        return str(self.email)


class MembershipStatus(models.TextChoices):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Membership(models.Model):
    """A user's role in one tenant."""

    Status = MembershipStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    user = ref("accounts.User")
    role = models.TextField(choices=Role)
    status = models.TextField(
        choices=Status, default=MembershipStatus.ACTIVE, db_default=MembershipStatus.ACTIVE
    )
    invited_by = ref("accounts.User", null=True, db_column="invited_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "memberships"
        constraints = [
            one_of("role", Role.values, "memberships_role_check"),
            one_of("status", MembershipStatus.values, "memberships_status_check"),
            models.UniqueConstraint(
                fields=["tenant", "user"], name="memberships_tenant_id_user_id_key"
            ),
        ]
        indexes = [models.Index(fields=["user"], name="memberships_user_idx")]


class AuthSession(models.Model):
    """A refresh-token session. Only the SHA-256 of the opaque token is stored.

    Each refresh creates a new row in the same family; presenting an already
    rotated token revokes the whole family (token theft detection).
    """

    id = uuid7_pk()
    user = ref("accounts.User")
    tenant = ref("tenants.Tenant", null=True)
    family_id = models.UUIDField()
    refresh_token_hash = models.BinaryField()
    device_label = models.TextField(null=True)  # noqa: DJ001
    ip = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(null=True)  # noqa: DJ001
    created_at = created_at()
    expires_at = models.DateTimeField()
    rotated_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "auth_sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["refresh_token_hash"], name="auth_sessions_refresh_token_hash_key"
            ),
            models.CheckConstraint(
                condition=Q(refresh_token_hash__octet_length=32),
                name="auth_sessions_refresh_token_hash_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user"], condition=Q(revoked_at__isnull=True), name="auth_sessions_user_idx"
            ),
            models.Index(fields=["family_id"], name="auth_sessions_family_idx"),
        ]
