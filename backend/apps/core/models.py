from django.db import models
from django.db.models import Q

from apps.core.db import SQLDefault, created_at, length_between, one_of, ref, tenant_ref, uuid7_pk


class IdempotencyKeyState(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class IdempotencyKey(models.Model):
    """Makes POST retries safe: same key + same body → the stored response is replayed."""

    State = IdempotencyKeyState
    id = uuid7_pk()
    tenant = tenant_ref()
    user = ref("accounts.User")
    key = models.TextField()
    request_method = models.TextField()
    request_path = models.TextField()
    request_hash = models.BinaryField()
    state = models.TextField(
        choices=State,
        default=IdempotencyKeyState.IN_PROGRESS,
        db_default=IdempotencyKeyState.IN_PROGRESS,
    )
    response_status = models.SmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    created_at = created_at()
    expires_at = models.DateTimeField(
        db_default=SQLDefault("(now() + '24:00:00'::interval)", models.DateTimeField())
    )

    class Meta:
        db_table = "idempotency_keys"
        constraints = [
            length_between("key", 16, 100, "idempotency_keys_key_check"),
            models.CheckConstraint(
                condition=Q(request_hash__octet_length=32),
                name="idempotency_keys_request_hash_check",
            ),
            one_of("state", IdempotencyKeyState.values, "idempotency_keys_state_check"),
            models.UniqueConstraint(
                fields=["tenant", "user", "key"], name="idempotency_keys_tenant_id_user_id_key_key"
            ),
        ]
        indexes = [models.Index(fields=["expires_at"], name="idempotency_keys_expiry_idx")]
