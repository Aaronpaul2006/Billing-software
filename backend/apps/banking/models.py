"""Bank statements (Part B): lines imported from the bank's file, matched by a
person to a payment in or out, or ignored. The table, its rules and its
row-level security are SQL (the migration, as db/schema.sql)."""

from django.db import models

from apps.core.db import created_at, ref, tenant_ref, updated_at, uuid7_pk
from apps.core.managers import TenantScoped


class BankLineStatus(models.TextChoices):
    OPEN = "OPEN"  # still to match
    MATCHED = "MATCHED"
    IGNORED = "IGNORED"  # bank charges, transfers between own accounts...


class BankLine(TenantScoped):
    Status = BankLineStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    account_label = models.TextField()
    line_date = models.DateField()
    narration = models.TextField()
    reference = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    money_in = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    money_out = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    balance = models.DecimalField(max_digits=16, decimal_places=2, null=True)
    fingerprint = models.TextField()
    status = models.TextField(
        choices=Status, default=BankLineStatus.OPEN, db_default=BankLineStatus.OPEN
    )
    payment = ref("payments.Payment", null=True)
    vendor_payment = ref("payables.VendorPayment", null=True)
    note = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "bank_lines"
