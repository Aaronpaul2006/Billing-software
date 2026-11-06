"""Payables (Part B): vendor bills, payments to vendors and what they settle.

The tables, constraints, the amount_paid trigger and the row-level security are
written in SQL (apps/payables/sql.py, the same text as db/schema.sql): these
models only read and write them.
"""

from django.db import models

from apps.core.db import created_at, ref, tenant_ref, updated_at, uuid7_pk
from apps.core.managers import TenantScoped
from apps.expenses.models import ExpenseCategory as Category
from apps.payments.models import PaymentMode, PaymentStatus


class VendorBill(TenantScoped):
    """A bill from a vendor or subcontractor, as we received it."""

    Status = PaymentStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    vendor_party = ref("parties.Party")
    project = ref("projects.Project", null=True)
    bill_number = models.TextField()
    bill_date = models.DateField()
    due_date = models.DateField(null=True)
    category = models.TextField(choices=Category)
    description = models.TextField()
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    itc_eligible = models.BooleanField(default=False, db_default=False)
    tds_section = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    tds_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, db_default=0)
    tds_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    net_payable = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    attachment = ref("files.Attachment", null=True)
    notes = models.TextField(null=True)  # noqa: DJ001
    status = models.TextField(
        choices=Status, default=PaymentStatus.RECORDED, db_default=PaymentStatus.RECORDED
    )
    voided_at = models.DateTimeField(null=True)
    voided_by = ref("accounts.User", null=True, db_column="voided_by")
    void_reason = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "vendor_bills"


class VendorPayment(TenantScoped):
    """Money we paid a vendor."""

    Status = PaymentStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    vendor_party = ref("parties.Party")
    project = ref("projects.Project", null=True)
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    mode = models.TextField(choices=PaymentMode)
    reference = models.TextField(null=True)  # noqa: DJ001 - UTR / cheque number
    notes = models.TextField(null=True)  # noqa: DJ001
    status = models.TextField(
        choices=Status, default=PaymentStatus.RECORDED, db_default=PaymentStatus.RECORDED
    )
    voided_at = models.DateTimeField(null=True)
    voided_by = ref("accounts.User", null=True, db_column="voided_by")
    void_reason = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "vendor_payments"


class VendorAllocation(TenantScoped):
    """Part of a payment set against a vendor bill (immutable; delete to undo)."""

    id = uuid7_pk()
    tenant = tenant_ref()
    vendor_payment = ref("payables.VendorPayment", related_name="allocations")
    vendor_bill = ref("payables.VendorBill", related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()

    class Meta:
        db_table = "vendor_allocations"
