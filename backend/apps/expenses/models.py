from django.db import models
from django.db.models import F, Q

from apps.core.db import (
    created_at,
    length_between,
    non_negative,
    one_of,
    ref,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)
from apps.payments.models import PaymentMode


class ExpenseStatus(models.TextChoices):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class ExpenseCategory(models.TextChoices):
    MATERIAL = "MATERIAL"
    LABOUR = "LABOUR"
    SUBCONTRACT = "SUBCONTRACT"
    EQUIPMENT = "EQUIPMENT"
    TRANSPORT = "TRANSPORT"
    SITE_OVERHEAD = "SITE_OVERHEAD"
    OFFICE = "OFFICE"
    OTHER = "OTHER"


class Expense(models.Model):
    """A site or office expense. Tracks its own payment until payables exist."""

    Category = ExpenseCategory
    Status = ExpenseStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    project = ref("projects.Project", null=True)
    vendor_party = ref("parties.Party", null=True)
    category = models.TextField(choices=Category)
    expense_date = models.DateField()
    description = models.TextField()
    vendor_bill_number = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    itc_eligible = models.BooleanField(default=False, db_default=False)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    payment_mode = models.TextField(choices=PaymentMode, null=True)  # noqa: DJ001
    attachment = ref("files.Attachment", null=True)
    status = models.TextField(
        choices=Status, default=ExpenseStatus.RECORDED, db_default=ExpenseStatus.RECORDED
    )
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "expenses"
        constraints = [
            tenant_id_key("expenses"),
            one_of("category", ExpenseCategory.values, "expenses_category_check"),
            length_between("description", 1, 1000, "expenses_description_check"),
            models.CheckConstraint(
                condition=Q(vendor_bill_number__char_length__lte=50),
                name="expenses_vendor_bill_number_check",
            ),
            non_negative("taxable_value", "expenses_taxable_value_check"),
            non_negative("gst_amount", "expenses_gst_amount_check"),
            one_of("payment_mode", PaymentMode.values, "expenses_payment_mode_check"),
            one_of("status", ExpenseStatus.values, "expenses_status_check"),
            models.CheckConstraint(
                condition=Q(total_amount=F("taxable_value") + F("gst_amount")),
                name="expenses_total_check",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=F("total_amount")),
                name="expenses_amount_paid_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "project", "-expense_date"], name="expenses_project_idx"
            ),
            models.Index(fields=["tenant", "-expense_date"], name="expenses_date_idx"),
        ]
