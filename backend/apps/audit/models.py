from django.db import models

from apps.core.db import SQLDefault, one_of


class AuditLogAction(models.TextChoices):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class AuditLog(models.Model):
    """Append-only trail written by the audit_row_change trigger.

    The app role can only SELECT (its own tenant's rows); the table rejects
    UPDATE, DELETE and TRUNCATE even for the owner. tenant_id / actor_user_id
    are plain columns, not foreign keys: the log outlives what it describes.
    """

    Action = AuditLogAction
    id = models.BigAutoField(primary_key=True)  # GENERATED ALWAYS (set in the RunSQL migration)
    tenant_id = models.UUIDField()
    occurred_at = models.DateTimeField(
        db_default=SQLDefault("clock_timestamp()", models.DateTimeField())
    )
    actor_user_id = models.UUIDField(null=True)
    request_id = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    action = models.TextField(choices=Action)
    table_name = models.TextField()
    row_id = models.UUIDField()
    old_data = models.JSONField(null=True)
    new_data = models.JSONField(null=True)

    class Meta:
        db_table = "audit_log"
        constraints = [one_of("action", AuditLogAction.values, "audit_log_action_check")]
        indexes = [
            models.Index(
                fields=["tenant_id", "table_name", "row_id", "occurred_at"],
                name="audit_log_row_idx",
            ),
            models.Index(fields=["tenant_id", "-occurred_at"], name="audit_log_tenant_idx"),
        ]
