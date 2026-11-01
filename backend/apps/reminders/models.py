from django.db import models
from django.db.models import Q

from apps.core.db import (
    CITextField,
    created_at,
    length_between,
    one_of,
    ref,
    tenant_id_key,
    tenant_ref,
    uuid7_pk,
)
from apps.core.managers import TenantScoped


class ReminderStage(models.TextChoices):
    BEFORE_DUE = "BEFORE_DUE"  # 3 days before the due date
    ON_DUE = "ON_DUE"
    OVERDUE_7 = "OVERDUE_7"
    OVERDUE_15 = "OVERDUE_15"
    OVERDUE_30 = "OVERDUE_30"
    MANUAL = "MANUAL"  # sent by a member from the bill


class PaymentReminder(TenantScoped):
    """One reminder emailed to a client about an unpaid bill (db/schema.sql §5).
    A log: written once, never changed; each automatic stage at most once per bill."""

    Stage = ReminderStage
    id = uuid7_pk()
    tenant = tenant_ref()
    document = ref("documents.Document")
    stage = models.TextField(choices=ReminderStage)
    sent_to = CITextField()
    amount_due = models.DecimalField(max_digits=14, decimal_places=2)
    sent_by = ref("accounts.User", null=True, db_column="sent_by")
    sent_at = created_at()

    class Meta:
        db_table = "payment_reminders"
        constraints = [
            tenant_id_key("payment_reminders"),
            one_of("stage", ReminderStage.values, "payment_reminders_stage_check"),
            length_between("sent_to", 3, 254, "payment_reminders_sent_to_check"),
            models.CheckConstraint(
                condition=Q(amount_due__gt=0), name="payment_reminders_amount_due_check"
            ),
            models.UniqueConstraint(
                fields=["tenant", "document", "stage"],
                condition=~Q(stage="MANUAL"),
                name="payment_reminders_stage_once",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "document", "-sent_at"], name="payment_reminders_document_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.stage} reminder to {self.sent_to}"
