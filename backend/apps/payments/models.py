from django.db import models
from django.db.models import Q

from apps.core.db import (
    NumNonNulls,
    created_at,
    one_of,
    ref,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)


class PaymentMode(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER"
    UPI = "UPI"
    CHEQUE = "CHEQUE"
    CASH = "CASH"
    CARD = "CARD"
    OTHER = "OTHER"


class PaymentStatus(models.TextChoices):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class Payment(models.Model):
    """Money received from a party."""

    Status = PaymentStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    party = ref("parties.Party")
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
        db_table = "payments"
        constraints = [
            tenant_id_key("payments"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payments_amount_check"),
            one_of("mode", PaymentMode.values, "payments_mode_check"),
            models.CheckConstraint(
                condition=Q(reference__char_length__lte=100), name="payments_reference_check"
            ),
            one_of("status", PaymentStatus.values, "payments_status_check"),
            models.CheckConstraint(
                condition=Q(status__ne="VOIDED")
                | (Q(voided_at__isnull=False) & Q(void_reason__isnull=False)),
                name="payments_void_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "party", "-payment_date"], name="payments_party_idx"),
            models.Index(fields=["tenant", "-payment_date"], name="payments_date_idx"),
        ]


class Allocation(models.Model):
    """Settles a document from a payment or an issued credit note.

    Immutable: the allocations trigger keeps documents.amount_settled in step
    and rejects over-allocation, even under concurrent requests.
    """

    id = uuid7_pk()
    tenant = tenant_ref()
    document = ref("documents.Document")  # the invoice / debit note being settled
    payment = ref("payments.Payment", null=True)
    credit_note = ref("documents.Document", null=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()

    class Meta:
        db_table = "allocations"
        constraints = [
            tenant_id_key("allocations"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="allocations_amount_check"),
            models.CheckConstraint(
                condition=models.lookups.Exact(NumNonNulls("payment", "credit_note"), 1),
                name="allocations_one_source_check",
            ),
            models.UniqueConstraint(
                fields=["document", "payment"],
                condition=Q(payment__isnull=False),
                name="allocations_payment_uq",
            ),
            models.UniqueConstraint(
                fields=["document", "credit_note"],
                condition=Q(credit_note__isnull=False),
                name="allocations_cn_uq",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "payment"], name="allocations_payment_idx")]
