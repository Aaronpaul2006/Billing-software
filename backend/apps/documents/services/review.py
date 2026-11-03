"""The last look before a bill is issued (B.14): warnings in plain words.

Only warnings: nothing here stops a bill being issued (the issue endpoint
keeps its own hard rules). Issued documents have nothing left to review.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from apps.catalog.models import CatalogItem, CatalogItemVariant
from apps.core.india import fy_start_year
from apps.core.tenancy import Principal
from apps.parties.models import Party
from apps.tenants.models import DocumentSeries

from ..models import GST_DOC_TYPES, Document, DocumentLine
from ..pdf.render import TITLES, inr
from .drafts import get_document
from .rates import last_rates

PAYABLE = frozenset({"TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE", "PROFORMA"})
B2B_TYPES = frozenset({"TAX_INVOICE", "DEBIT_NOTE"})
FAR_BELOW = Decimal("0.75")  # a rate more than 25 % under the usual one
SAME_TOTAL = Decimal("0.01")  # within 1 %
DUPLICATE_DAYS = 7
# The 4th letter of a PAN says who holds it: P is a person; C company, F firm,
# and so on are businesses, which are usually GST-registered.
PERSON_PAN = "P"


def _warning(code: str, message: str, line_no: int | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "line_no": line_no}


def _client(doc: Document, party: Party) -> list[dict[str, Any]]:
    if doc.doc_type not in B2B_TYPES or party.gstin or party.gst_treatment != "UNREGISTERED":
        return []
    business = bool(party.pan) and party.pan[3] != PERSON_PAN
    return [
        _warning(
            "client_no_gstin",
            f"{party.display_name} has no GSTIN saved, so this bill goes in GST returns as a"
            " sale to an unregistered buyer and they cannot claim the tax back."
            + (" Their PAN is a business's PAN: they are probably registered." if business else "")
            + " If they have a GSTIN, add it on the client's page before issuing.",
        )
    ]


def _due(doc: Document) -> list[dict[str, Any]]:
    if doc.doc_type in PAYABLE and doc.due_date is None:
        return [
            _warning(
                "no_due_date",
                "There is no due date: the bill will never show as overdue and no payment"
                " reminders go out.",
            )
        ]
    return []


def _series(doc: Document) -> list[dict[str, Any]]:
    fy = fy_start_year(doc.doc_date)
    found = DocumentSeries.objects.filter(
        gst_registration_id=doc.gst_registration_id,
        doc_type=doc.doc_type,
        fy_start_year=fy,
        is_active=True,
    ).exists()
    if found:
        return []
    kind = TITLES.get(doc.doc_type, doc.doc_type).lower()
    return [
        _warning(
            "no_number_series",
            f"There is no number series for {kind}s in the financial year"
            f" {fy}-{(fy + 1) % 100:02d}: the bill cannot be issued until one is added"
            " (Settings, Number series).",
        )
    ]


def _usual_rates(principal: Principal, doc: Document) -> dict[tuple[Any, Any], Decimal]:
    """The rate last charged to this client per item (and variant), else the catalog rate."""
    usual: dict[tuple[Any, Any], Decimal] = {}
    lines = list(DocumentLine.objects.filter(document_id=doc.pk, catalog_item_id__isnull=False))
    if not lines:
        return usual
    items = {ln.catalog_item_id for ln in lines}
    defaults = dict(
        CatalogItem.objects.filter(pk__in=items, default_rate__isnull=False).values_list(
            "id", "default_rate"
        )
    )
    deltas = dict(
        CatalogItemVariant.objects.filter(catalog_item_id__in=items).values_list("id", "rate_delta")
    )
    for ln in lines:
        base = defaults.get(ln.catalog_item_id)
        if base is not None:
            usual[(ln.catalog_item_id, ln.catalog_variant_id)] = base + deltas.get(
                ln.catalog_variant_id, Decimal(0)
            )
    for r in last_rates(principal, doc.party_id):
        usual[(r["catalog_item_id"], r["catalog_variant_id"])] = r["rate"]
    return usual


def _rates(principal: Principal, doc: Document, lines: list[DocumentLine]) -> list[dict[str, Any]]:
    usual = _usual_rates(principal, doc)
    out = []
    for ln in lines:
        before = usual.get((ln.catalog_item_id, ln.catalog_variant_id))
        if before and ln.rate < before * FAR_BELOW:
            out.append(
                _warning(
                    "rate_below_usual",
                    f'Line {ln.line_no} "{ln.description}": rate ₹{inr(ln.rate)} is far below'
                    f" the usual ₹{inr(before)}. Check it is not a typing mistake.",
                    ln.line_no,
                )
            )
    return out


def _duplicate(doc: Document) -> list[dict[str, Any]]:
    total = doc.grand_total
    window = (doc.doc_date - timedelta(days=DUPLICATE_DAYS), doc.doc_date)
    others = (
        Document.objects.filter(
            party_id=doc.party_id,
            doc_type=doc.doc_type,
            status__in=["ISSUED", "ACCEPTED"],
            doc_date__range=window,
            grand_total__gte=total * (1 - SAME_TOTAL),
            grand_total__lte=total * (1 + SAME_TOTAL),
        )
        .exclude(pk=doc.pk)
        .order_by("-doc_date")
    )
    return [
        _warning(
            "possible_duplicate",
            f"{o.doc_number} dated {o.doc_date:%d-%m-%Y} for the same client has almost the same"
            f" total (₹{inr(o.grand_total)}). Make sure this is not the same bill twice.",
        )
        for o in others[:3]
    ]


def _hsn(doc: Document, lines: list[DocumentLine]) -> list[dict[str, Any]]:
    if doc.doc_type not in GST_DOC_TYPES:
        return []
    return [
        _warning(
            "missing_hsn",
            f'Line {ln.line_no} "{ln.description}" has no HSN / SAC code; GST bills need one'
            " (works contracts: 9954).",
            ln.line_no,
        )
        for ln in lines
        if not ln.sac_hsn
    ]


def review(principal: Principal, doc_id: uuid.UUID) -> list[dict[str, Any]]:
    doc = get_document(principal, doc_id)  # tenant.read; another tenant's: 404
    if doc.status != "DRAFT":
        return []
    party = Party.objects.get(pk=doc.party_id)
    lines = list(DocumentLine.objects.filter(document_id=doc.pk).order_by("line_no"))
    return [
        *_series(doc),
        *_client(doc, party),
        *_duplicate(doc),
        *_due(doc),
        *_hsn(doc, lines),
        *_rates(principal, doc, lines),
    ]
