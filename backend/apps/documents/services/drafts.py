"""Draft documents: create, edit, delete, preview (docs/02-api-design.md §5).

The client never sends tax amounts, totals, place of supply or supply type:
they are derived here and computed by the tax engine on every save.

* registration: the project's billing registration, else the tenant default;
* place of supply: the project's site state (works on immovable property,
  IGST Act s.12(3)); without a project the party's state; else our own;
* supply category: SEZ when the client is an SEZ unit / developer (always
  inter-State); EXPORT when the client is overseas and there is no Indian
  site (place of supply 96); REGULAR otherwise. An overseas client of works
  on a site in India is a domestic supply: the site decides;
* LUT (zero-rated without IGST): SEZ and exports only; defaults to on when the
  registration has a Letter of Undertaking for the document's financial year;
* reverse charge: chosen by the user, for registered clients in India;
* deductions: from the project (retention, TDS, GST TDS, advance recovery
  capped at the advance still outstanding), for invoices and proformas.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum

from apps.catalog.models import CatalogItem, CatalogItemVariant
from apps.core.errors import Conflict, Invalid
from apps.core.india import FOREIGN_COUNTRY, fy_start_year
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.parties.models import Party
from apps.projects.models import BoqItem, Project
from apps.tenants.models import GstRegistration

from ..models import Document, DocumentLine
from ..tax import Deductions, DocumentIn, DocumentOut, LineIn, LineOut, TaxError, compute
from ..tax.engine import GST_DOC_TYPES, ZERO_RATED
from . import ra_bills

DRAFTABLE_TYPES = ("QUOTATION", "PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY")
NOTE_TYPES = frozenset({"CREDIT_NOTE", "DEBIT_NOTE"})  # created via their own endpoints
DEDUCTION_TYPES = frozenset({"PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"})
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Resolved:
    """What a document payload refers to, checked and loaded."""

    registration: GstRegistration
    party: Party
    project: Project | None
    place_of_supply: str
    supply_category: str = "REGULAR"


@dataclass(frozen=True)
class Computed:
    resolved: Resolved
    lines: list[dict[str, Any]]  # stored line fields, inputs filled in
    out: DocumentOut
    lut: bool = False
    reverse_charge: bool = False


# --- resolving references -------------------------------------------------------------


def _resolve(data: dict[str, Any]) -> Resolved:
    project = None
    if data.get("project_id"):
        project = get_or_invalid(Project, data["project_id"], "project_id", label="project")
        if project.status == "CANCELLED":
            raise Invalid("project_id", "This project is cancelled.", code="inactive")

    party = get_or_invalid(Party, data["party_id"], "party_id", label="party")
    if not party.is_customer:
        raise Invalid("party_id", "This party is not a customer.", code="not_a_customer")
    if not party.is_active:
        raise Invalid("party_id", "This party is archived.", code="inactive")
    if project and project.client_party_id != party.pk:
        raise Invalid("party_id", "Bill the project's client.", code="party_mismatch")

    if data.get("gst_registration_id"):
        registration = get_or_invalid(
            GstRegistration,
            data["gst_registration_id"],
            "gst_registration_id",
            label="GST registration",
        )
        if project and project.gst_registration_id != registration.pk:
            raise Invalid(
                "gst_registration_id",
                "This project is billed from another registration.",
                code="registration_mismatch",
            )
    elif project:
        registration = GstRegistration.objects.get(pk=project.gst_registration_id)
    else:
        default: GstRegistration | None = GstRegistration.objects.filter(is_default=True).first()
        if default is None:
            raise Invalid("gst_registration_id", "Add a GST registration first.", code="required")
        registration = default
    if not registration.is_active:
        raise Invalid("gst_registration_id", "This GST registration is inactive.", code="inactive")

    if party.gst_treatment == "SEZ":
        category = "SEZ"
    elif party.gst_treatment == "OVERSEAS" and project is None:
        category = "EXPORT"
    else:
        category = "REGULAR"
    if category == "EXPORT":
        place = FOREIGN_COUNTRY
    else:
        place = project.site_state_code if project else party.state_code or registration.state_code
    return Resolved(registration, party, project, place, category)


def _lut(data: dict[str, Any], resolved: Resolved) -> bool:
    """Zero-rated supplies go under the registration's LUT unless the user
    chose to pay IGST; anything else never does."""
    if resolved.supply_category not in ZERO_RATED:
        return False
    registration = resolved.registration
    fy = fy_start_year(data["doc_date"])
    has_lut = registration.lut_fy_start_year == fy
    wanted = data.get("lut")
    if wanted is None:
        return has_lut
    if wanted and not has_lut:
        raise Invalid(
            "lut",
            f"No Letter of Undertaking for {fy}-{(fy + 1) % 100:02d} on this registration: add it"
            " in the GST registration, or charge IGST.",
            code="no_lut",
        )
    return bool(wanted)


def _reverse_charge(data: dict[str, Any], resolved: Resolved) -> bool:
    if not data.get("reverse_charge"):
        return False
    if data["doc_type"] not in GST_DOC_TYPES:
        raise Invalid(
            "reverse_charge",
            "Only tax invoices and their notes can be under reverse charge.",
            code="reverse_charge_not_allowed",
        )
    if not resolved.party.gstin or resolved.supply_category != "REGULAR":
        raise Invalid(
            "reverse_charge",
            "Reverse charge applies to registered clients in India (outside SEZs).",
            code="reverse_charge_not_allowed",
        )
    return True


def _line_inputs(lines: list[dict[str, Any]], project: Project | None) -> list[dict[str, Any]]:
    """Fill gaps from the catalog item / BOQ item a line names."""
    filled = []
    for i, line in enumerate(lines):
        line = dict(line)
        source: CatalogItem | BoqItem | None = None
        if line.get("boq_item_id"):
            source = get_or_invalid(
                BoqItem, line["boq_item_id"], f"lines[{i}].boq_item_id", label="BOQ item"
            )
            if project is None or source.project_id != project.pk:
                raise Invalid(
                    f"lines[{i}].boq_item_id",
                    "This BOQ item belongs to another project.",
                    code="boq_item_mismatch",
                )
            defaults: dict[str, Any] = {"rate": source.rate}
        elif line.get("catalog_item_id"):
            source = get_or_invalid(
                CatalogItem,
                line["catalog_item_id"],
                f"lines[{i}].catalog_item_id",
                label="catalog item",
            )
            defaults = {"rate": source.default_rate}
        else:
            defaults = {}
        if line.get("catalog_variant_id") and not line.get("catalog_item_id"):
            raise Invalid(
                f"lines[{i}].catalog_variant_id",
                "A variant needs its catalog item.",
                code="variant_without_item",
            )
        if source is not None:
            defaults |= {
                "description": source.description or getattr(source, "name", None),
                "unit": source.unit,
                "sac_hsn": source.sac_hsn,
                "gst_rate": source.gst_rate,
            }
        if line.get("catalog_variant_id") and isinstance(source, CatalogItem):
            variant = get_or_invalid(
                CatalogItemVariant,
                line["catalog_variant_id"],
                f"lines[{i}].catalog_variant_id",
                label="variant",
            )
            if variant.catalog_item_id != source.pk:
                raise Invalid(
                    f"lines[{i}].catalog_variant_id",
                    "This variant belongs to another catalog item.",
                    code="variant_mismatch",
                )
            base = source.default_rate
            rate = None if base is None else base + variant.rate_delta
            if rate is not None and rate < 0:
                raise Invalid(
                    f"lines[{i}].catalog_variant_id",
                    "The variant takes the rate below zero.",
                    code="negative_rate",
                )
            defaults["rate"] = rate
            defaults["description"] = (
                f"{defaults['description']} — {variant.attribute}: {variant.value}"
            )
        for key, value in defaults.items():
            if line.get(key) in (None, "") and value is not None:
                line[key] = value
        for key, label in (("description", "description"), ("rate", "rate")):
            if line.get(key) in (None, ""):
                raise Invalid(f"lines[{i}].{key}", f"A {label} is required.", code="required")
        line.setdefault("discount_amount", ZERO)
        line.setdefault("gst_rate", ZERO)
        filled.append(line)
    return filled


def _advance_outstanding(project: Project, exclude: uuid.UUID | None) -> Decimal:
    recovered = (
        (
            Document.objects.filter(project_id=project.pk, status="ISSUED")
            .exclude(pk=exclude)
            .aggregate(total=Sum("advance_recovery_amount"))["total"]
        )
        or ZERO
    )
    return max(project.mobilisation_advance - recovered, ZERO)


def _deductions(doc_type: str, project: Project | None, doc_id: uuid.UUID | None) -> Deductions:
    if project is None or doc_type not in DEDUCTION_TYPES:
        return Deductions()
    return Deductions(
        retention_pct=project.retention_pct,
        income_tax_tds_pct=project.income_tax_tds_pct,
        gst_tds_applicable=project.gst_tds_applicable,
        advance_recovery_pct=project.advance_recovery_pct,
        advance_outstanding=_advance_outstanding(project, doc_id),
    )


def _compute(data: dict[str, Any], doc_id: uuid.UUID | None = None) -> Computed:
    resolved = _resolve(data)
    ra_bills.check_header(data, resolved.project)
    lines = _line_inputs(data.get("lines", []), resolved.project)
    ra_bills.check_lines(data, resolved.project, lines, doc_id)
    lut = _lut(data, resolved)
    reverse_charge = _reverse_charge(data, resolved)
    engine_in = DocumentIn(
        doc_type=data["doc_type"],
        registration_type=resolved.registration.registration_type,
        supplier_state=resolved.registration.state_code,
        place_of_supply=resolved.place_of_supply,
        lines=[
            LineIn(
                quantity=ln["quantity"],
                rate=ln["rate"],
                gst_rate=ln["gst_rate"],
                discount=ln["discount_amount"],
            )
            for ln in lines
        ],
        round_to_rupee=data.get("round_to_rupee", False),
        deductions=_deductions(data["doc_type"], resolved.project, doc_id),
        supply_category=resolved.supply_category,
        lut=lut,
        reverse_charge=reverse_charge,
    )
    try:
        out = compute(engine_in) if lines else _empty(engine_in)
    except TaxError as exc:
        field = exc.field.replace(".discount", ".discount_amount")
        raise Invalid(field, str(exc), code=exc.code) from exc
    return Computed(resolved, lines, out, lut, reverse_charge)


def _empty(doc: DocumentIn) -> DocumentOut:
    """A draft may be saved before it has lines: all totals zero."""
    if doc.registration_type != "REGULAR" and doc.doc_type in GST_DOC_TYPES:
        raise TaxError(
            "doc_type",
            f"A {doc.registration_type} registration cannot issue "
            f"{doc.doc_type}; use BILL_OF_SUPPLY.",
            "doc_type_not_allowed",
        )
    intra = doc.supply_category not in ZERO_RATED and doc.place_of_supply == doc.supplier_state
    zero = {f: ZERO for f in HEADER_TOTALS if f != "supply_type"}
    return DocumentOut(supply_type="INTRA_STATE" if intra else "INTER_STATE", lines=[], **zero)


# --- persistence -----------------------------------------------------------------------

HEADER_TOTALS = (
    "supply_type",
    "subtotal",
    "cgst_amount",
    "sgst_amount",
    "igst_amount",
    "cess_amount",
    "round_off",
    "grand_total",
    "retention_amount",
    "income_tax_tds_amount",
    "gst_tds_amount",
    "advance_recovery_amount",
    "net_receivable",
)
HEADER_INPUTS = (
    "doc_type",
    "doc_date",
    "due_date",
    "valid_until",
    "notes",
    "terms",
    "round_to_rupee",
)


def _header(c: Computed, data: dict[str, Any]) -> dict[str, Any]:
    return {
        **{f: data.get(f) for f in HEADER_INPUTS if f in data},
        "gst_registration_id": c.resolved.registration.pk,
        "party_id": c.resolved.party.pk,
        "project_id": c.resolved.project.pk if c.resolved.project else None,
        "place_of_supply": c.resolved.place_of_supply,
        "supply_category": c.resolved.supply_category,
        "lut": c.lut,
        "reverse_charge": c.reverse_charge,
        **{f: getattr(c.out, f) for f in HEADER_TOTALS},
    }


def _write_lines(doc: Document, c: Computed) -> None:
    DocumentLine.objects.bulk_create(
        DocumentLine(
            tenant_id=doc.tenant_id,
            document=doc,
            line_no=i,
            catalog_item_id=ln.get("catalog_item_id"),
            catalog_variant_id=ln.get("catalog_variant_id"),
            boq_item_id=ln.get("boq_item_id"),
            description=ln["description"],
            sac_hsn=ln.get("sac_hsn") or None,
            unit=ln.get("unit") or None,
            quantity=ln["quantity"],
            prev_cumulative_qty=ln.get("prev_cumulative_qty"),
            rate=ln["rate"],
            discount_amount=ln["discount_amount"],
            gst_rate=ln["gst_rate"],
            **_line_amounts(out),
        )
        for i, (ln, out) in enumerate(zip(c.lines, c.out.lines, strict=True), start=1)
    )


def _line_amounts(out: LineOut) -> dict[str, Decimal]:
    return {
        "taxable_value": out.taxable_value,
        "cgst_amount": out.cgst_amount,
        "sgst_amount": out.sgst_amount,
        "igst_amount": out.igst_amount,
        "cess_amount": out.cess_amount,
        "line_total": out.line_total,
    }


def _stored_lines(doc: Document) -> list[dict[str, Any]]:
    return [
        {
            f: getattr(ln, f)
            for f in (
                "catalog_item_id",
                "catalog_variant_id",
                "boq_item_id",
                "description",
                "sac_hsn",
                "unit",
                "quantity",
                "rate",
                "discount_amount",
                "gst_rate",
            )
        }
        for ln in DocumentLine.objects.filter(document_id=doc.pk).order_by("line_no")
    ]


def current_state(doc: Document) -> dict[str, Any]:
    """A stored document as a payload: input to recompute, convert, notes."""
    return {
        "doc_type": doc.doc_type,
        "gst_registration_id": doc.gst_registration_id,
        "party_id": doc.party_id,
        "project_id": doc.project_id,
        "doc_date": doc.doc_date,
        "due_date": doc.due_date,
        "valid_until": doc.valid_until,
        "notes": doc.notes,
        "terms": doc.terms,
        "round_to_rupee": doc.round_to_rupee,
        "is_ra_bill": doc.is_ra_bill,
        "lut": doc.lut,
        "reverse_charge": doc.reverse_charge,
        "lines": _stored_lines(doc),
    }


# --- use cases ----------------------------------------------------------------------------


def preview(principal: Principal, data: dict[str, Any]) -> Computed:
    require(principal, "documents.draft")
    return _compute(data)


def get_document(principal: Principal, doc_id: uuid.UUID) -> Document:
    require(principal, "tenant.read")
    return get_or_404(Document, doc_id)


def create_draft(principal: Principal, data: dict[str, Any]) -> Document:
    require(principal, "documents.draft")
    return _create(principal, data)


def _create(principal: Principal, data: dict[str, Any], **links: uuid.UUID) -> Document:
    """Insert a draft; `links` sets source_document_id / original_document_id."""
    c = _compute(data)
    with transaction.atomic():
        doc = Document(
            **_header(c, data),
            **ra_bills.ra_fields(data, c.resolved.project),
            **links,
            status="DRAFT",
            created_by_id=principal.user_id,
        )
        doc.save()
        _write_lines(doc, c)
    return get_or_404(Document, doc.pk)


def update_draft(
    principal: Principal, doc_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> Document:
    require(principal, "documents.draft")
    with transaction.atomic():
        doc = get_or_404(Document, doc_id, for_update=True)
        if doc.status != "DRAFT":
            raise Conflict(
                "Only drafts can be edited; issue a credit or debit note instead.",
                code="document_not_draft",
            )
        if doc.doc_type in NOTE_TYPES and changes.get("doc_type", doc.doc_type) != doc.doc_type:
            raise Invalid("doc_type", "A credit or debit note keeps its type.", code="not_allowed")
        current = current_state(doc)
        if "party_id" in changes or "project_id" in changes:
            current.pop("gst_registration_id")  # re-derive unless sent again
        merged = {**current, **changes}
        if merged.get("valid_until") and merged["doc_type"] != "QUOTATION":
            raise Invalid(
                "valid_until", "Only quotations have a validity date.", code="not_allowed"
            )
        if merged.get("due_date") and merged["due_date"] < merged["doc_date"]:
            raise Invalid("due_date", "Due before the document date.", code="invalid_dates")
        c = _compute(merged, doc_id=doc.pk)
        update_versioned(
            Document.objects,
            doc.pk,
            expected,
            **_header(c, merged),
            **ra_bills.ra_fields(merged, c.resolved.project, doc),
        )
        DocumentLine.objects.filter(document_id=doc.pk).delete()
        _write_lines(doc, c)
    return get_or_404(Document, doc_id)


def delete_draft(principal: Principal, doc_id: uuid.UUID) -> None:
    require(principal, "documents.draft")
    with transaction.atomic():
        doc = get_or_404(Document, doc_id, for_update=True)
        if doc.status != "DRAFT":
            raise Conflict(
                "Only drafts can be deleted; cancel it instead.", code="document_not_draft"
            )
        doc.delete()  # lines go with it (ON DELETE CASCADE)
