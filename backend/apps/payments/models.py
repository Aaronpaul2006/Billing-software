from django.db import models
from django.db.models import F, Q

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
from apps.core.managers import TenantScoped


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


class Payment(TenantScoped):
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


class RetentionBook(models.TextChoices):
    GST = "GST"  # retention deducted on tax invoices
    NON_GST = "NON_GST"  # ... on bills of supply


class RetentionReleaseStatus(models.TextChoices):
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class RetentionRelease(TenantScoped):
    """Retention money the client now releases: not a tax document (GST was
    charged on the invoices), only money due, settled by payments through
    allocations. amount_settled is maintained by the allocations trigger."""

    Book = RetentionBook
    Status = RetentionReleaseStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    project = ref("projects.Project")
    party = ref("parties.Party")  # the project's client
    book = models.TextField(choices=Book)
    release_date = models.DateField()
    due_date = models.DateField(null=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    amount_settled = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    reference = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    notes = models.TextField(null=True)  # noqa: DJ001
    status = models.TextField(
        choices=Status,
        default=RetentionReleaseStatus.RELEASED,
        db_default=RetentionReleaseStatus.RELEASED,
    )
    cancelled_at = models.DateTimeField(null=True)
    cancelled_by = ref("accounts.User", null=True, db_column="cancelled_by")
    cancel_reason = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "retention_releases"
        constraints = [
            tenant_id_key("retention_releases"),
            one_of("book", RetentionBook.values, "retention_releases_book_check"),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="retention_releases_amount_check"
            ),
            models.CheckConstraint(
                condition=Q(reference__char_length__lte=50),
                name="retention_releases_reference_check",
            ),
            models.CheckConstraint(
                condition=Q(notes__char_length__lte=2000), name="retention_releases_notes_check"
            ),
            one_of("status", RetentionReleaseStatus.values, "retention_releases_status_check"),
            models.CheckConstraint(
                condition=Q(amount_settled__gte=0) & Q(amount_settled__lte=F("amount")),
                name="retention_releases_amount_settled_check",
            ),
            models.CheckConstraint(
                condition=Q(status__ne="CANCELLED")
                | (
                    Q(cancelled_at__isnull=False)
                    & Q(cancel_reason__isnull=False)
                    & Q(amount_settled=0)
                ),
                name="retention_releases_cancel_check",
            ),
            models.CheckConstraint(
                condition=Q(due_date__isnull=True) | Q(due_date__gte=F("release_date")),
                name="retention_releases_due_date_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "project", "-release_date"],
                name="retention_releases_project_idx",
            )
        ]

    def __str__(self) -> str:
        return f"Retention release {self.amount} ({self.status})"


class Allocation(TenantScoped):
    """Settles a document from a payment or an issued credit note, or a
    retention release from a payment.

    Immutable: the allocations trigger keeps documents / retention_releases
    amount_settled in step and rejects over-allocation, even under
    concurrent requests.
    """

    id = uuid7_pk()
    tenant = tenant_ref()
    document = ref("documents.Document", null=True)  # the invoice / debit note being settled
    retention_release = ref("payments.RetentionRelease", null=True)  # or the release
    payment = ref("payments.Payment", null=True, related_name="allocations")
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
            models.CheckConstraint(
                condition=models.lookups.Exact(NumNonNulls("document", "retention_release"), 1),
                name="allocations_one_target_check",
            ),
            models.CheckConstraint(
                condition=Q(retention_release__isnull=True) | Q(payment__isnull=False),
                name="allocations_release_from_payment_check",
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
            models.UniqueConstraint(
                fields=["retention_release", "payment"],
                condition=Q(retention_release__isnull=False),
                name="allocations_release_uq",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "payment"], name="allocations_payment_idx")]
