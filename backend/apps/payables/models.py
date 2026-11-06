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
    # RA bills against a subcontract work order (payables part 2)
    work_order = ref("payables.WorkOrder", null=True, related_name="ra_bills")
    ra_number = models.IntegerField(null=True)
    retention_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
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


class WorkOrderStatus(models.TextChoices):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WorkOrder(TenantScoped):
    """Work let to a subcontractor on one project, item by item at agreed rates."""

    Status = WorkOrderStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    project = ref("projects.Project")
    vendor_party = ref("parties.Party")
    wo_number = models.TextField()
    wo_date = models.DateField()
    title = models.TextField()
    terms = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    retention_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0, db_default=0)
    tds_section = models.TextField(null=True)  # noqa: DJ001
    tds_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, db_default=0)
    status = models.TextField(
        choices=WorkOrderStatus, default=WorkOrderStatus.OPEN, db_default=WorkOrderStatus.OPEN
    )
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "work_orders"


class WorkOrderItem(TenantScoped):
    """One item of a work order: what, how much was agreed, at what rate."""

    id = uuid7_pk()
    tenant = tenant_ref()
    work_order = ref("payables.WorkOrder", related_name="items")
    boq_item = ref("projects.BoqItem", null=True)
    item_code = models.TextField()
    description = models.TextField()
    unit = models.TextField()
    sac_hsn = models.TextField(null=True)  # noqa: DJ001
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    rate = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18, db_default=18)
    sort_order = models.IntegerField(default=0, db_default=0)
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "work_order_items"


class VendorBillLine(TenantScoped):
    """This RA bill's quantity of one work order item (written once)."""

    id = uuid7_pk()
    tenant = tenant_ref()
    vendor_bill = ref("payables.VendorBill", related_name="lines")
    work_order_item = ref("payables.WorkOrderItem", related_name="bill_lines")
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    rate = models.DecimalField(max_digits=14, decimal_places=2)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    created_at = created_at()

    class Meta:
        db_table = "vendor_bill_lines"


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
    vendor_bill = ref("payables.VendorBill", null=True, related_name="allocations")
    vendor_retention_release = ref(
        "payables.VendorRetentionRelease", null=True, related_name="allocations"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()

    class Meta:
        db_table = "vendor_allocations"


class ReleaseStatus(models.TextChoices):
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class VendorRetentionRelease(TenantScoped):
    """Retention held from a subcontractor's RA bills, released to be paid."""

    Status = ReleaseStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    work_order = ref("payables.WorkOrder", related_name="releases")
    vendor_party = ref("parties.Party")
    release_date = models.DateField()
    due_date = models.DateField(null=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    reference = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    notes = models.TextField(null=True)  # noqa: DJ001
    status = models.TextField(
        choices=ReleaseStatus, default=ReleaseStatus.RELEASED, db_default=ReleaseStatus.RELEASED
    )
    cancelled_at = models.DateTimeField(null=True)
    cancelled_by = ref("accounts.User", null=True, db_column="cancelled_by")
    cancel_reason = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "vendor_retention_releases"
