"""RA (running account) bills and the BOQ quantity cap
(docs/01-architecture.md §5.5).

An RA bill is an invoice, bill of supply or proforma for a project whose every
line bills a BOQ item, once. Each line stores the quantity in this bill and a
snapshot of the quantity billed before it, so the bill shows previous / this
bill / up to date without recomputing history.

"Billed" means lines of issued tax invoices and bills of supply (RA or not).
Billing beyond an item's contract quantity is allowed only for variation
items, checked on every save and again at issue with the BOQ rows locked, so
concurrent bills cannot overshoot together.

RA numbers run per project and document type and are given when the draft is
created, under a lock on the project row. One RA draft per project and type
may be open at a time, so bills are issued in their order. A cancelled RA
bill keeps its number; when it was the latest, the replacement reuses it
(the unique index ignores cancelled bills).
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.db.models import Max, Sum

from apps.core.errors import Conflict, Invalid
from apps.projects.models import BoqItem, Project

from ..models import Document, DocumentLine

RA_TYPES = frozenset({"PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"})
BILLED_TYPES = ("TAX_INVOICE", "BILL_OF_SUPPLY")  # what counts as billed quantity
ZERO_QTY = Decimal("0.000")


def billed_quantities(
    boq_item_ids: Iterable[uuid.UUID], exclude_document: uuid.UUID | None = None
) -> dict[uuid.UUID, Decimal]:
    """Quantity billed per BOQ item in issued tax invoices / bills of supply."""
    rows = (
        DocumentLine.objects.filter(
            boq_item_id__in=list(boq_item_ids),
            document__status="ISSUED",
            document__doc_type__in=BILLED_TYPES,
        )
        .exclude(document_id=exclude_document)
        .values("boq_item_id")
        .annotate(total=Sum("quantity"))
    )
    return {r["boq_item_id"]: r["total"] for r in rows}


def check_header(data: dict[str, Any], project: Project | None) -> None:
    """Before the lines: what can be an RA bill."""
    if not data.get("is_ra_bill"):
        return
    if data["doc_type"] not in RA_TYPES:
        raise Invalid(
            "is_ra_bill",
            "Only tax invoices, bills of supply and proformas can be RA bills.",
            code="not_allowed",
        )
    if project is None:
        raise Invalid("project_id", "An RA bill needs a project.", code="required")


def check_lines(
    data: dict[str, Any],
    project: Project | None,
    lines: list[dict[str, Any]],
    doc_id: uuid.UUID | None,
) -> None:
    """RA bill lines and the BOQ cap. Sets `prev_cumulative_qty` on RA lines."""
    is_ra = bool(data.get("is_ra_bill"))
    if is_ra:
        seen: dict[uuid.UUID, int] = {}
        for i, line in enumerate(lines):
            boq_id = line.get("boq_item_id")
            if not boq_id:
                raise Invalid(
                    f"lines[{i}].boq_item_id",
                    "Every RA bill line bills a BOQ item; add extra work to the BOQ"
                    " as a variation item.",
                    code="required",
                )
            if boq_id in seen:
                raise Invalid(
                    f"lines[{i}].boq_item_id",
                    f"This BOQ item is already on line {seen[boq_id] + 1}.",
                    code="duplicate_boq_item",
                )
            seen[boq_id] = i

    ids = {line["boq_item_id"] for line in lines if line.get("boq_item_id")}
    if not ids or not (is_ra or data["doc_type"] in BILLED_TYPES):
        return
    billed = billed_quantities(ids, exclude_document=doc_id)
    items = {item.pk: item for item in BoqItem.objects.filter(pk__in=ids)}
    this_bill: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO_QTY)
    for i, line in enumerate(lines):
        boq_id = line.get("boq_item_id")
        if not boq_id:
            continue
        item, before = items[boq_id], billed.get(boq_id, ZERO_QTY)
        if is_ra:
            line["prev_cumulative_qty"] = before
        this_bill[boq_id] += line["quantity"]
        up_to_date = before + this_bill[boq_id]
        if not item.is_variation and up_to_date > item.contract_qty:
            raise Invalid(
                f"lines[{i}].quantity",
                f"Item {item.item_code}: contract quantity {item.contract_qty:f} {item.unit},"
                f" billed so far {before:f}, this bill would take it to {up_to_date:f}."
                " Mark the item as a variation to bill beyond the contract.",
                code="exceeds_boq_quantity",
            )


def lock_boq_items(lines: Iterable[dict[str, Any]]) -> None:
    """At issue: lock the BOQ rows a document bills, in a fixed order (no
    deadlocks), so concurrent bills see each other's quantities."""
    ids = sorted({line["boq_item_id"] for line in lines if line.get("boq_item_id")})
    if ids:
        list(BoqItem.objects.select_for_update().filter(pk__in=ids).order_by("pk"))


def ra_fields(
    data: dict[str, Any], project: Project | None, doc: Document | None = None
) -> dict[str, Any]:
    """`is_ra_bill` / `ra_sequence` for a document being saved (after
    `check_lines`). Call inside the transaction that writes it: assigning a
    number locks the project."""
    if not data.get("is_ra_bill") or project is None:
        return {"is_ra_bill": False, "ra_sequence": None}
    project_id, doc_type = project.pk, data["doc_type"]
    if (
        doc is not None
        and doc.is_ra_bill
        and doc.project_id == project_id
        and doc.doc_type == doc_type
    ):
        return {"is_ra_bill": True, "ra_sequence": doc.ra_sequence}
    list(Project.objects.select_for_update().filter(pk=project_id))  # serialise per project
    ra_bills = Document.objects.filter(
        project_id=project_id, doc_type=doc_type, is_ra_bill=True
    ).exclude(pk=doc.pk if doc else None)
    open_draft = ra_bills.filter(status="DRAFT").values_list("ra_sequence", flat=True).first()
    if open_draft is not None:
        raise Conflict(
            f"RA bill {open_draft} of this project is still a draft; issue or delete it first.",
            code="ra_draft_exists",
        )
    last = ra_bills.exclude(status="CANCELLED").aggregate(m=Max("ra_sequence"))["m"] or 0
    return {"is_ra_bill": True, "ra_sequence": last + 1}
