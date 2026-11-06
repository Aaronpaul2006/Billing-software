"""Payables (Part B): record vendor bills, pay them, void either. The database
keeps what was paid on each bill (db/schema.sql 7d); these rules come first so
people get a plain message, not a database error."""

import uuid
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.parties.models import Party
from apps.projects.models import Project

from .models import VendorAllocation, VendorBill, VendorPayment
from .tds import tds_amount

RECORD = "payments.record"


def _vendor(vendor_id: uuid.UUID) -> Party:
    vendor = get_or_invalid(Party, vendor_id, "vendor_party_id", label="vendor")
    if not vendor.is_vendor:
        raise Invalid(
            "vendor_party_id",
            "This party is not marked as a vendor (tick Vendor on its page).",
            code="not_a_vendor",
        )
    return vendor


def _amounts(data: dict[str, Any]) -> dict[str, Any]:
    """Total, TDS and what we pay, worked out here (never trusted from the client)."""
    taxable: Decimal = data["taxable_value"]
    gst: Decimal = data.get("gst_amount") or Decimal("0.00")
    section = data.get("tds_section") or None
    rate: Decimal = data.get("tds_rate") or Decimal("0.00")
    if rate > 0 and section is None:
        raise Invalid("tds_section", "Say which section the TDS is under.", code="required")
    tds = tds_amount(taxable, rate) if section else Decimal("0.00")
    total = taxable + gst
    return {
        "gst_amount": gst,
        "total_amount": total,
        "tds_section": section,
        "tds_rate": rate if section else Decimal("0.00"),
        "tds_amount": tds,
        "net_payable": total - tds,
    }


def _check_dates(data: dict[str, Any]) -> None:
    if data.get("due_date") and data["due_date"] < data["bill_date"]:
        raise Invalid("due_date", "The due date is before the bill's date.", code="invalid")


def _check_project(data: dict[str, Any]) -> None:
    if data.get("project_id"):
        get_or_invalid(Project, data["project_id"], "project_id", label="project")


def _number_free(vendor_id: uuid.UUID, number: str, exclude: uuid.UUID | None = None) -> None:
    taken = VendorBill.objects.filter(
        vendor_party_id=vendor_id, status="RECORDED", bill_number__iexact=number
    )
    if exclude:
        taken = taken.exclude(pk=exclude)
    if taken.exists():
        raise Invalid(
            "bill_number",
            "This vendor's bill with this number is already entered.",
            code="duplicate",
        )


def record_bill(principal: Principal, data: dict[str, Any]) -> VendorBill:
    require(principal, RECORD)
    _vendor(data["vendor_party_id"])
    _check_project(data)
    _check_dates(data)
    _number_free(data["vendor_party_id"], data["bill_number"])
    bill = VendorBill(**{**data, **_amounts(data)}, created_by_id=principal.user_id)
    bill.save()
    return get_or_404(VendorBill, bill.pk)


def update_bill(
    principal: Principal, bill_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> VendorBill:
    """Edit a vendor bill until something is paid against it."""
    require(principal, RECORD)
    with transaction.atomic():
        bill = get_or_404(VendorBill, bill_id, for_update=True)
        if bill.status != "RECORDED":
            raise Conflict("This bill is voided.", code="vendor_bill_voided")
        if bill.amount_paid > 0:
            raise Conflict(
                "Payments are set against this bill; undo them first to change it.",
                code="vendor_bill_paid",
            )
        if bill.work_order_id:
            raise Conflict(
                "An RA bill is not edited: void it and enter it again from its work order.",
                code="ra_bill_edit",
            )
        merged = {
            f: getattr(bill, f)
            for f in (
                "vendor_party_id",
                "project_id",
                "bill_number",
                "bill_date",
                "due_date",
                "taxable_value",
                "gst_amount",
                "tds_section",
                "tds_rate",
            )
        }
        merged.update(changes)
        if "vendor_party_id" in changes:
            _vendor(merged["vendor_party_id"])
        _check_project(changes)
        _check_dates(merged)
        _number_free(merged["vendor_party_id"], merged["bill_number"], exclude=bill.pk)
        update_versioned(VendorBill.objects, bill.pk, expected, **{**changes, **_amounts(merged)})
    return get_or_404(VendorBill, bill_id)


def void_bill(principal: Principal, bill_id: uuid.UUID, expected: int, reason: str) -> VendorBill:
    require(principal, RECORD)
    with transaction.atomic():
        bill = get_or_404(VendorBill, bill_id, for_update=True)
        if bill.status == "VOIDED":
            raise Conflict("This bill is already voided.", code="vendor_bill_voided")
        if bill.amount_paid > 0:
            raise Conflict(
                "Payments are set against this bill; void those payments first.",
                code="vendor_bill_paid",
            )
        update_versioned(
            VendorBill.objects,
            bill.pk,
            expected,
            status="VOIDED",
            voided_at=timezone.now(),
            voided_by_id=principal.user_id,
            void_reason=reason,
        )
    return get_or_404(VendorBill, bill_id)


def _allocate(principal: Principal, payment: VendorPayment, items: list[dict[str, Any]]) -> None:
    available = payment.amount - sum(
        (a.amount for a in VendorAllocation.objects.filter(vendor_payment=payment)),
        Decimal("0.00"),
    )
    seen: set[uuid.UUID] = set()
    for i, item in enumerate(items):
        field = f"allocations[{i}]"
        bill = get_or_invalid(
            VendorBill, item["vendor_bill_id"], f"{field}.vendor_bill_id", label="vendor bill"
        )
        if bill.pk in seen:
            raise Invalid(f"{field}.vendor_bill_id", "Listed twice.", code="duplicate")
        seen.add(bill.pk)
        if bill.vendor_party_id != payment.vendor_party_id:
            raise Invalid(
                f"{field}.vendor_bill_id", "It is another vendor's bill.", code="party_mismatch"
            )
        if bill.status != "RECORDED":
            raise Invalid(f"{field}.vendor_bill_id", "This bill is voided.", code="voided")
        amount: Decimal = item["amount"]
        owed = bill.net_payable - bill.amount_paid
        if amount > owed:
            raise Invalid(
                f"{field}.amount", f"More than the {owed} still owed.", code="exceeds_outstanding"
            )
        if amount > available:
            raise Invalid(
                f"{field}.amount",
                f"More than the payment's unallocated {available}.",
                code="exceeds_payment",
            )
        available -= amount
        try:
            with transaction.atomic():
                VendorAllocation(
                    vendor_payment=payment,
                    vendor_bill=bill,
                    amount=amount,
                    created_by_id=principal.user_id,
                ).save()
        except DatabaseError as exc:  # paid concurrently: the row lock lost the race
            raise Invalid(
                f"{field}.amount", "Someone paid this bill just now; reload.", code="conflict"
            ) from exc


def record_payment(principal: Principal, data: dict[str, Any]) -> VendorPayment:
    require(principal, RECORD)
    _vendor(data["vendor_party_id"])
    _check_project(data)
    items = data.pop("allocations", None) or []
    with transaction.atomic():
        payment = VendorPayment(**data, created_by_id=principal.user_id)
        payment.save()
        payment = VendorPayment.objects.select_for_update().get(pk=payment.pk)
        _allocate(principal, payment, items)
    return get_or_404(VendorPayment, payment.pk)


def void_payment(
    principal: Principal, payment_id: uuid.UUID, expected: int, reason: str
) -> VendorPayment:
    """Void (never delete) a payment; what it paid on bills is undone first."""
    require(principal, RECORD)
    with transaction.atomic():
        payment = get_or_404(VendorPayment, payment_id, for_update=True)
        if payment.status == "VOIDED":
            raise Conflict("This payment is already voided.", code="payment_voided")
        VendorAllocation.objects.filter(vendor_payment=payment).delete()
        update_versioned(
            VendorPayment.objects,
            payment.pk,
            expected,
            status="VOIDED",
            voided_at=timezone.now(),
            voided_by_id=principal.user_id,
            void_reason=reason,
        )
    return get_or_404(VendorPayment, payment_id)
