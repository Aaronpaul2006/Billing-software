from django.db import models
from django.db.models import Q

from apps.core.db import (
    SQLDefault,
    created_at,
    length_between,
    one_of,
    ref,
    tenant_id_key,
    tenant_ref,
    uuid7_pk,
)
from apps.core.managers import TenantScoped


class ExportKind(models.TextChoices):
    DOCUMENTS = "DOCUMENTS"
    PAYMENTS = "PAYMENTS"
    EXPENSES = "EXPENSES"
    RECEIVABLES = "RECEIVABLES"
    GSTR1 = "GSTR1"
    BOQ = "BOQ"  # one project's BOQ: contract vs billed
    PROJECTS = "PROJECTS"  # the project margins report


class ExportFormat(models.TextChoices):
    CSV = "CSV"
    XLSX = "XLSX"
    JSON = "JSON"


class ExportStatus(models.TextChoices):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class Export(TenantScoped):
    """A file exported for a user, written by a background job; rows and files
    are purged after 7 days (db/schema.sql §6, §8)."""

    Kind = ExportKind
    Format = ExportFormat
    Status = ExportStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    kind = models.TextField(choices=ExportKind)
    format = models.TextField(choices=ExportFormat)
    params = models.JSONField(
        default=dict, db_default=SQLDefault("'{}'::jsonb", models.JSONField())
    )
    status = models.TextField(
        choices=ExportStatus, default=ExportStatus.PENDING, db_default=ExportStatus.PENDING
    )
    file_name = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    storage_key = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    size_bytes = models.BigIntegerField(null=True)
    row_count = models.IntegerField(null=True)
    warnings = models.JSONField(
        default=list, db_default=SQLDefault("'[]'::jsonb", models.JSONField())
    )
    error = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    requested_by = ref("accounts.User", db_column="requested_by")
    created_at = created_at()
    finished_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "exports"
        constraints = [
            tenant_id_key("exports"),
            models.UniqueConstraint(fields=["storage_key"], name="exports_storage_key_key"),
            one_of("kind", ExportKind.values, "exports_kind_check"),
            one_of("format", ExportFormat.values, "exports_format_check"),
            one_of("status", ExportStatus.values, "exports_status_check"),
            length_between("file_name", 1, 200, "exports_file_name_check"),
            models.CheckConstraint(condition=Q(size_bytes__gte=0), name="exports_size_bytes_check"),
            models.CheckConstraint(condition=Q(row_count__gte=0), name="exports_row_count_check"),
            models.CheckConstraint(
                condition=Q(error__char_length__lte=1000), name="exports_error_check"
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "requested_by", "-created_at"], name="exports_requested_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.format} ({self.status})"
