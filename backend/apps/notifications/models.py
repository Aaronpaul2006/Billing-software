"""Notifications (Part B). The table is written in SQL (db/schema.sql, the same
text as the migration); this model only reads and writes it."""

from django.db import models

from apps.core.db import created_at, ref, tenant_ref, uuid7_pk
from apps.core.managers import TenantScoped


class Kind(models.TextChoices):
    QUOTATION_ACCEPTED = "QUOTATION_ACCEPTED"
    QUOTATION_DECLINED = "QUOTATION_DECLINED"
    BILLS_OVERDUE = "BILLS_OVERDUE"
    PAYABLES_DUE = "PAYABLES_DUE"
    MEMBER_JOINED = "MEMBER_JOINED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    BILL_APPROVED = "BILL_APPROVED"


class Notification(TenantScoped):
    """Something one person should look at, with where to look."""

    Kind = Kind
    id = uuid7_pk()
    tenant = tenant_ref()
    user = ref("accounts.User")
    kind = models.TextField(choices=Kind)
    title = models.TextField()
    body = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    link = models.TextField(null=True)  # noqa: DJ001
    dedupe_key = models.TextField()
    read_at = models.DateTimeField(null=True)
    created_at = created_at()

    class Meta:
        db_table = "notifications"
