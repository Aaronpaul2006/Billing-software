"""Site and office expenses (docs/02-api-design.md §6).

Expenses track their own payment (amount_paid) until payables / vendor bills
exist. Never deleted: voided instead (the audit trail records who and when).
"""

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.files.models import Attachment
from apps.parties.models import Party
from apps.projects.models import Project

from .models import Expense

ZERO = Decimal("0.00")
FIELDS = (
    "project_id",
    "vendor_party_id",
    "category",
    "expense_date",
    "description",
    "vendor_bill_number",
    "taxable_value",
    "gst_amount",
    "itc_eligible",
    "amount_paid",
    "payment_mode",
    "attachment_id",
)


def get_expense(principal: Principal, expense_id: uuid.UUID) -> Expense:
    require(principal, "tenant.read")
    return get_or_404(Expense, expense_id)


def _check(merged: dict[str, Any]) -> dict[str, Any]:
    """Rules on the resulting expense; returns it with the derived total."""
    if merged.get("project_id"):
        get_or_invalid(Project, merged["project_id"], "project_id", label="project")
    if merged.get("vendor_party_id"):
        vendor = get_or_invalid(Party, merged["vendor_party_id"], "vendor_party_id", label="party")
        if not vendor.is_vendor:
            raise Invalid("vendor_party_id", "This party is not a vendor.", code="not_a_vendor")
    if merged.get("attachment_id"):
        attachment = get_or_invalid(
            Attachment, merged["attachment_id"], "attachment_id", label="attachment"
        )
        if attachment.status != "AVAILABLE":
            raise Invalid("attachment_id", "The file is not available.", code="not_available")
    gst = merged.get("gst_amount") or ZERO
    total = merged["taxable_value"] + gst
    if merged.get("itc_eligible") and gst <= 0:
        raise Invalid("itc_eligible", "Input tax credit needs a GST amount.", code="no_gst")
    paid = merged.get("amount_paid") or ZERO
    if paid > total:
        raise Invalid("amount_paid", f"More than the total {total}.", code="exceeds_total")
    if paid > 0 and not merged.get("payment_mode"):
        raise Invalid("payment_mode", "Say how it was paid.", code="required")
    return {**merged, "gst_amount": gst, "amount_paid": paid, "total_amount": total}


def record_expense(principal: Principal, data: dict[str, Any]) -> Expense:
    require(principal, "expenses.record")
    values = _check(data)
    expense = Expense(**values, created_by_id=principal.user_id)
    expense.save()
    return expense


def update_expense(
    principal: Principal, expense_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> Expense:
    require(principal, "expenses.record")
    with transaction.atomic():
        expense = get_or_404(Expense, expense_id, for_update=True)
        if expense.status == "VOIDED":
            raise Conflict("This expense is voided.", code="expense_voided")
        current = {f: getattr(expense, f) for f in FIELDS}
        values = _check({**current, **changes})
        update_versioned(
            Expense.objects,
            expense.pk,
            expected,
            **{k: v for k, v in values.items() if k in (*FIELDS, "total_amount")},
        )
    return get_or_404(Expense, expense_id)


def void_expense(principal: Principal, expense_id: uuid.UUID, expected: int) -> Expense:
    require(principal, "expenses.record")
    with transaction.atomic():
        expense = get_or_404(Expense, expense_id, for_update=True)
        if expense.status == "VOIDED":
            raise Conflict("This expense is already voided.", code="expense_voided")
        update_versioned(Expense.objects, expense.pk, expected, status="VOIDED")
    return get_or_404(Expense, expense_id)
