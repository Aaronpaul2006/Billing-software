"""Subcontract work orders and the RA bills received against them (Part B,
payables part 2). The database keeps the quantities honest (db/schema.sql
7e); these rules come first so people get a plain message.

An RA bill's value is worked out here, never taken from the client: each
line is this bill's quantity of a work order item at the item's rate (rounded
to the paisa), GST per line at the item's rate, TDS on the value before GST
(rounded to the rupee, as on any vendor bill) and retention at the work
order's percentage, held back from what we pay now.
"""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Max, Sum

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.projects.models import BoqItem, Project

from .models import VendorBill, VendorBillLine, WorkOrder, WorkOrderItem
from .services import RECORD, _vendor
from .tds import tds_amount

PAISA = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


# --- work orders -------------------------------------------------------------


def next_number(project: Project) -> str:
    n = WorkOrder.objects.filter(project=project).count() + 1
    while True:
        number = f"WO/{project.code}/{n:02d}"
        if not WorkOrder.objects.filter(wo_number__iexact=number).exists():
            return number
        n += 1


def _check_items(project_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
    if not items:
        raise Invalid("items", "Add at least one item.", code="required")
    codes: dict[str, int] = {}
    for i, item in enumerate(items):
        code = item["item_code"].strip().lower()
        if code in codes:
            raise Invalid(
                f"items[{i}].item_code", f"Also on line {codes[code] + 1}.", code="duplicate"
            )
        codes[code] = i
        if item.get("boq_item_id"):
            boq = get_or_invalid(
                BoqItem, item["boq_item_id"], f"items[{i}].boq_item_id", label="BOQ item"
            )
            if boq.project_id != project_id:
                raise Invalid(
                    f"items[{i}].boq_item_id",
                    "This BOQ item is on another project.",
                    code="project_mismatch",
                )


def _tds(data: dict[str, Any]) -> dict[str, Any]:
    section = data.get("tds_section") or None
    rate: Decimal = data.get("tds_rate") or Decimal("0.00")
    if rate > 0 and section is None:
        raise Invalid("tds_section", "Say which section the TDS is under.", code="required")
    return {"tds_section": section, "tds_rate": rate if section else Decimal("0.00")}


def _number_free(number: str, exclude: uuid.UUID | None = None) -> None:
    taken = WorkOrder.objects.filter(wo_number__iexact=number)
    if exclude:
        taken = taken.exclude(pk=exclude)
    if taken.exists():
        raise Invalid("wo_number", "A work order with this number exists.", code="duplicate")


def create(principal: Principal, data: dict[str, Any]) -> WorkOrder:
    require(principal, RECORD)
    project = get_or_invalid(Project, data["project_id"], "project_id", label="project")
    _vendor(data["vendor_party_id"])
    items = data.pop("items")
    _check_items(project.pk, items)
    data["wo_number"] = (data.get("wo_number") or "").strip() or next_number(project)
    _number_free(data["wo_number"])
    with transaction.atomic():
        wo = WorkOrder(**{**data, **_tds(data)}, created_by_id=principal.user_id)
        wo.save()
        WorkOrderItem.objects.bulk_create(
            [
                WorkOrderItem(**item, work_order=wo, tenant_id=principal.tenant_id, sort_order=i)
                for i, item in enumerate(items)
            ]
        )
    return get_or_404(WorkOrder, wo.pk)


def update(
    principal: Principal, wo_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> WorkOrder:
    """Change the terms or the items. Items keep their id; one missing from the
    list is removed (only if nothing is billed on it); a quantity can be raised
    (an amendment) but not cut below what is billed."""
    require(principal, RECORD)
    items = changes.pop("items", None)
    with transaction.atomic():
        wo = get_or_404(WorkOrder, wo_id, for_update=True)
        if "wo_number" in changes:
            changes["wo_number"] = changes["wo_number"].strip() or wo.wo_number
            _number_free(changes["wo_number"], exclude=wo.pk)
        if "tds_section" in changes or "tds_rate" in changes:
            changes.update(
                _tds(
                    {
                        "tds_section": changes.get("tds_section", wo.tds_section),
                        "tds_rate": changes.get("tds_rate", wo.tds_rate),
                    }
                )
            )
        update_versioned(WorkOrder.objects, wo.pk, expected, **changes)
        if items is not None:
            _replace_items(principal, wo, items)
    return get_or_404(WorkOrder, wo_id)


def _replace_items(principal: Principal, wo: WorkOrder, items: list[dict[str, Any]]) -> None:
    _check_items(wo.project_id, items)
    billed = billed_qty(wo)
    existing = {i.pk: i for i in WorkOrderItem.objects.filter(work_order=wo)}
    keep: set[uuid.UUID] = set()
    for n, item in enumerate(items):
        item_id = item.pop("id", None)
        if item_id is None:
            WorkOrderItem.objects.create(
                **item, work_order=wo, tenant_id=principal.tenant_id, sort_order=n
            )
            continue
        if item_id not in existing:
            raise Invalid(f"items[{n}].id", "Not an item of this work order.", code="not_found")
        keep.add(item_id)
        done = billed.get(item_id, Decimal("0"))
        if item["qty"] < done:
            raise Invalid(
                f"items[{n}].qty",
                f"{done} is already billed; the quantity cannot be less.",
                code="below_billed",
            )
        WorkOrderItem.objects.filter(pk=item_id).update(**item, sort_order=n)
    for item_id, old in existing.items():
        if item_id in keep:
            continue
        if billed.get(item_id):
            raise Invalid(
                "items",
                f"Item {old.item_code} is billed; it cannot be removed.",
                code="item_billed",
            )
        old.delete()


def set_status(principal: Principal, wo_id: uuid.UUID, expected: int, status: str) -> WorkOrder:
    require(principal, RECORD)
    with transaction.atomic():
        wo = get_or_404(WorkOrder, wo_id, for_update=True)
        if wo.status == status:
            word = "closed" if status == "CLOSED" else "open"
            raise Conflict(f"This work order is already {word}.", code="work_order_status")
        update_versioned(WorkOrder.objects, wo.pk, expected, status=status)
    return get_or_404(WorkOrder, wo_id)


# --- progress ----------------------------------------------------------------


def billed_qty(wo: WorkOrder) -> dict[uuid.UUID, Decimal]:
    """Quantity billed so far on recorded RA bills, per item."""
    rows = (
        VendorBillLine.objects.filter(
            work_order_item__work_order=wo, vendor_bill__status="RECORDED"
        )
        .values("work_order_item_id")
        .annotate(q=Sum("qty"))
    )
    return {r["work_order_item_id"]: r["q"] for r in rows}


@dataclass
class Totals:
    value: Decimal  # the work order: qty x rate of every item
    billed: Decimal  # value of recorded RA bills
    retention_held: Decimal
    paid: Decimal
    ra_count: int


def totals(wo: WorkOrder) -> Totals:
    value = sum(
        (_money(i.qty * i.rate) for i in WorkOrderItem.objects.filter(work_order=wo)),
        Decimal("0.00"),
    )
    bills = VendorBill.objects.filter(work_order=wo, status="RECORDED").aggregate(
        billed=Sum("taxable_value"), held=Sum("retention_amount"), paid=Sum("amount_paid")
    )
    return Totals(
        value=value,
        billed=bills["billed"] or Decimal("0.00"),
        retention_held=bills["held"] or Decimal("0.00"),
        paid=bills["paid"] or Decimal("0.00"),
        ra_count=VendorBill.objects.filter(work_order=wo, status="RECORDED").count(),
    )


# --- RA bills ----------------------------------------------------------------


def ra_amounts(wo: WorkOrder, lines: list[tuple[WorkOrderItem, Decimal]]) -> dict[str, Decimal]:
    """Value, GST, TDS, retention and what we pay for these lines."""
    taxable, gst = Decimal("0.00"), Decimal("0.00")
    for item, qty in lines:
        amount = _money(qty * item.rate)
        taxable += amount
        gst += _money(amount * item.gst_rate / 100)
    tds = tds_amount(taxable, wo.tds_rate) if wo.tds_section else Decimal("0.00")
    retention = _money(taxable * wo.retention_pct / 100)
    return {
        "taxable_value": taxable,
        "gst_amount": gst,
        "total_amount": taxable + gst,
        "tds_amount": tds,
        "retention_amount": retention,
        "net_payable": taxable + gst - tds - retention,
    }


def record_ra_bill(principal: Principal, wo_id: uuid.UUID, data: dict[str, Any]) -> VendorBill:
    """Record the subcontractor's RA bill: this bill's quantity of each item."""
    require(principal, RECORD)
    with transaction.atomic():
        wo = get_or_404(WorkOrder, wo_id, for_update=True)
        if wo.status != "OPEN":
            raise Conflict(
                "This work order is closed; reopen it to enter a bill.", code="work_order_closed"
            )
        if data.get("due_date") and data["due_date"] < data["bill_date"]:
            raise Invalid("due_date", "The due date is before the bill's date.", code="invalid")
        items = {i.pk: i for i in WorkOrderItem.objects.filter(work_order=wo)}
        billed = billed_qty(wo)
        lines: list[tuple[WorkOrderItem, Decimal]] = []
        seen: set[uuid.UUID] = set()
        for n, line in enumerate(data["lines"]):
            field = f"lines[{n}]"
            item = items.get(line["work_order_item_id"])
            if item is None:
                raise Invalid(
                    f"{field}.work_order_item_id",
                    "Not an item of this work order.",
                    code="not_found",
                )
            if item.pk in seen:
                raise Invalid(f"{field}.work_order_item_id", "Listed twice.", code="duplicate")
            seen.add(item.pk)
            left = item.qty - billed.get(item.pk, Decimal("0"))
            if line["qty"] > left:
                raise Invalid(
                    f"{field}.qty",
                    f"Only {left.normalize():f} {item.unit} of item {item.item_code} is left on "
                    "the work order; amend the work order to bill more.",
                    code="exceeds_work_order",
                )
            lines.append((item, line["qty"]))
        if not lines:
            raise Invalid(
                "lines", "Enter this bill's quantity of at least one item.", code="required"
            )

        number = data.get("ra_number") or (
            (
                VendorBill.objects.filter(work_order=wo, status="RECORDED").aggregate(
                    n=Max("ra_number")
                )["n"]
                or 0
            )
            + 1
        )
        if VendorBill.objects.filter(work_order=wo, status="RECORDED", ra_number=number).exists():
            raise Invalid("ra_number", f"RA bill {number} is already entered.", code="duplicate")
        if VendorBill.objects.filter(
            vendor_party_id=wo.vendor_party_id,
            status="RECORDED",
            bill_number__iexact=data["bill_number"],
        ).exists():
            raise Invalid(
                "bill_number",
                "This vendor's bill with this number is already entered.",
                code="duplicate",
            )
        bill = VendorBill(
            vendor_party_id=wo.vendor_party_id,
            project_id=wo.project_id,
            work_order=wo,
            ra_number=number,
            bill_number=data["bill_number"],
            bill_date=data["bill_date"],
            due_date=data.get("due_date"),
            category=data.get("category") or "SUBCONTRACT",
            description=f"RA bill {number} · {wo.title}"[:1000],
            itc_eligible=data.get("itc_eligible", False),
            tds_section=wo.tds_section,
            tds_rate=wo.tds_rate,
            notes=data.get("notes"),
            attachment_id=data.get("attachment_id"),
            created_by_id=principal.user_id,
            **ra_amounts(wo, lines),
        )
        try:
            with transaction.atomic():
                bill.save()
                VendorBillLine.objects.bulk_create(
                    [
                        VendorBillLine(
                            tenant_id=principal.tenant_id,
                            vendor_bill=bill,
                            work_order_item=item,
                            qty=qty,
                            rate=item.rate,
                            amount=_money(qty * item.rate),
                            gst_rate=item.gst_rate,
                        )
                        for item, qty in lines
                    ]
                )
        except (IntegrityError, DatabaseError) as exc:  # another bill took the quantity first
            raise Conflict(
                "Someone entered a bill on this work order just now; reload and try again.",
                code="conflict",
            ) from exc
    return get_or_404(VendorBill, bill.pk)
