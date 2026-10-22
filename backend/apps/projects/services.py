"""Projects and their Bill of Quantities (docs/02-api-design.md §4)."""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Max, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ErrorDetail, ValidationError

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document, DocumentLine
from apps.documents.services.ra_bills import BILLED_TYPES, billed_quantities
from apps.parties.models import Party
from apps.tenants.models import GstRegistration

from . import boq_import
from .models import BoqItem, Project

# Once a document refers to the project these decide its tax treatment.
LOCKED_ONCE_BILLED = ("client_party_id", "gst_registration_id", "site_state_code")


def _check_references(data: dict[str, Any]) -> None:
    if "client_party_id" in data:
        party = get_or_invalid(Party, data["client_party_id"], "client_party_id", label="party")
        if not party.is_customer:
            raise Invalid("client_party_id", "This party is not a customer.", code="not_a_customer")
    if "gst_registration_id" in data:
        registration = get_or_invalid(
            GstRegistration,
            data["gst_registration_id"],
            "gst_registration_id",
            label="GST registration",
        )
        if not registration.is_active:
            raise Invalid(
                "gst_registration_id", "This GST registration is inactive.", code="inactive"
            )


def _code_taken(exc: IntegrityError) -> Conflict:
    return Conflict("Another project already uses this code.", code="code_taken")


def get_project(principal: Principal, project_id: uuid.UUID) -> Project:
    require(principal, "tenant.read")
    return get_or_404(Project, project_id)


def create_project(principal: Principal, data: dict[str, Any]) -> Project:
    require(principal, "masters.edit")
    _check_references(data)
    try:
        with transaction.atomic():
            project = Project(**data, created_by_id=principal.user_id)
            project.save()
    except IntegrityError as exc:
        raise _code_taken(exc) from exc
    return project


def update_project(
    principal: Principal, project_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> Project:
    require(principal, "masters.edit")
    try:
        with transaction.atomic():
            project = get_or_404(Project, project_id, for_update=True)
            touched = [
                f for f in LOCKED_ONCE_BILLED if f in changes and changes[f] != getattr(project, f)
            ]
            if touched and Document.objects.filter(project_id=project_id).exists():
                raise Conflict(
                    f"Documents refer to this project; {', '.join(touched)} cannot change.",
                    code="project_in_use",
                )
            _check_references(changes)
            update_versioned(Project.objects, project_id, expected, **changes)
    except IntegrityError as exc:
        raise _code_taken(exc) from exc
    return get_or_404(Project, project_id)


# --- BOQ items -----------------------------------------------------------------------


def _item_code_taken() -> Conflict:
    return Conflict("This project already has an item with this code.", code="item_code_taken")


def get_boq_item(principal: Principal, item_id: uuid.UUID) -> BoqItem:
    require(principal, "tenant.read")
    return get_or_404(BoqItem, item_id)


def create_boq_item(principal: Principal, project_id: uuid.UUID, data: dict[str, Any]) -> BoqItem:
    require(principal, "boq.edit")
    project = get_or_404(Project, project_id)
    try:
        with transaction.atomic():
            item = BoqItem(**data, project=project)
            item.save()
    except IntegrityError as exc:
        raise _item_code_taken() from exc
    return item


def update_boq_item(
    principal: Principal, item_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> BoqItem:
    require(principal, "boq.edit")
    try:
        with transaction.atomic():
            get_or_404(BoqItem, item_id, for_update=True)
            update_versioned(BoqItem.objects, item_id, expected, **changes)
            item = get_or_404(BoqItem, item_id)
            billed = billed_quantities([item.pk]).get(item.pk)
            if billed is not None and not item.is_variation and billed > item.contract_qty:
                raise Invalid(
                    "contract_qty" if "contract_qty" in changes else "is_variation",
                    f"{billed:f} {item.unit} is already billed, more than the contract"
                    f" quantity {item.contract_qty:f}.",
                    code="below_billed",
                )
    except IntegrityError as exc:
        raise _item_code_taken() from exc
    return item


def delete_boq_item(principal: Principal, item_id: uuid.UUID) -> None:
    require(principal, "boq.edit")
    with transaction.atomic():
        item = get_or_404(BoqItem, item_id, for_update=True)
        if DocumentLine.objects.filter(boq_item_id=item.pk).exists():
            raise Conflict(
                "This item has been billed and cannot be deleted.", code="boq_item_billed"
            )
        item.delete()


@dataclass
class BoqImport:
    dry_run: bool
    items: list[BoqItem]
    skipped_rows: list[int]
    ignored_columns: list[str]

    @property
    def count(self) -> int:
        return len(self.items)


MAX_ROW_ERRORS = 100


def import_boq_items(
    principal: Principal, project_id: uuid.UUID, data: bytes, *, dry_run: bool
) -> BoqImport:
    """Add BOQ items from a spreadsheet, all or nothing. Each row passes the
    same validation as a single item; codes must be new to the project and
    unique in the file. Errors name spreadsheet rows: `rows[7].rate`."""
    from .serializers import BoqItemWriteSerializer

    require(principal, "boq.edit")
    project = get_or_404(Project, project_id)
    sheet = boq_import.read(data)
    existing = set(BoqItem.objects.filter(project=project).values_list("item_code", flat=True))
    next_order = BoqItem.objects.filter(project=project).aggregate(m=Max("sort_order"))["m"] or 0
    errors: dict[int, Any] = {}
    seen: dict[str, int] = {}
    items: list[BoqItem] = []
    for position, (row, values) in enumerate(sheet.rows, start=1):
        if len(errors) >= MAX_ROW_ERRORS:
            break
        s = BoqItemWriteSerializer(data=values)
        if not s.is_valid():
            errors[row] = s.errors
            continue
        fields = dict(s.validated_data)
        code = fields["item_code"]
        if code in existing:
            errors[row] = {
                "item_code": [
                    ErrorDetail(
                        "This project already has an item with this code.", code="item_code_taken"
                    )
                ]
            }
        elif code in seen:
            errors[row] = {
                "item_code": [ErrorDetail(f"Also on row {seen[code]}.", code="duplicate_item_code")]
            }
        seen.setdefault(code, row)
        if "sort_order" not in values:
            fields["sort_order"] = next_order + position
        items.append(BoqItem(**fields, project=project, tenant_id=principal.tenant_id))
    if errors:
        raise ValidationError(cast(Any, {"rows": errors}))  # {row number: errors}, as many=True
    if not items:
        raise Invalid("file", "No item rows found.", code="no_rows")
    if dry_run:
        for item in items:  # a preview: nothing was saved, so no id or timestamps
            item.id = item.created_at = item.updated_at = None
    else:
        try:
            with transaction.atomic():
                BoqItem.objects.bulk_create(items)
        except IntegrityError as exc:  # someone added the same code meanwhile
            raise _item_code_taken() from exc
    return BoqImport(dry_run, items, sheet.skipped_rows, sheet.ignored_columns)


HUNDRED = Decimal("100")
CENTS = Decimal("0.01")


def boq_progress(principal: Principal, project_id: uuid.UUID) -> dict[str, Any]:
    """Per BOQ item: contract vs billed (issued tax invoices and bills of
    supply), for preparing the next RA bill. Variation items may go past
    100 % (negative balance)."""
    require(principal, "tenant.read")
    return boq_progress_rows(get_or_404(Project, project_id))


def boq_progress_rows(project: Project) -> dict[str, Any]:
    """boq_progress() for a loaded project (also used by the BOQ export)."""
    billed_lines = DocumentLine.objects.filter(
        boq_item_id=OuterRef("pk"),
        document__status="ISSUED",
        document__doc_type__in=BILLED_TYPES,
    ).values("boq_item_id")
    items = (
        BoqItem.objects.filter(project=project)
        .annotate(
            billed_qty=Coalesce(
                Subquery(billed_lines.annotate(t=Sum("quantity")).values("t")),
                Value(Decimal("0.000")),
            ),
            billed_value=Coalesce(
                Subquery(billed_lines.annotate(t=Sum("taxable_value")).values("t")),
                Value(Decimal("0.00")),
            ),
        )
        .order_by("sort_order", "item_code")
    )
    rows = []
    for item in items:
        contract_value = (item.contract_qty * item.rate).quantize(CENTS, ROUND_HALF_UP)
        rows.append(
            {
                "boq_item_id": item.pk,
                "item_code": item.item_code,
                "description": item.description,
                "unit": item.unit,
                "rate": item.rate,
                "is_variation": item.is_variation,
                "contract_qty": item.contract_qty,
                "billed_qty": item.billed_qty,
                "balance_qty": item.contract_qty - item.billed_qty,
                "contract_value": contract_value,
                "billed_value": item.billed_value,
                "progress_pct": _pct(item.billed_qty, item.contract_qty),
            }
        )
    contract = sum((r["contract_value"] for r in rows), Decimal("0.00"))
    billed = sum((r["billed_value"] for r in rows), Decimal("0.00"))
    return {
        "results": rows,
        "totals": {
            "contract_value": contract,
            "billed_value": billed,
            "progress_pct": _pct(billed, contract),
        },
    }


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part / whole * HUNDRED).quantize(CENTS, ROUND_HALF_UP) if whole else None
