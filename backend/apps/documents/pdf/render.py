"""Document PDFs: build the context, render HTML (auto-escaped Django
template, no user-controlled template content), convert with WeasyPrint.

The layout carries the tax-invoice particulars of CGST Rule 46: supplier and
recipient names, addresses and GSTINs, number and date, place of supply with
state name, HSN/SAC, quantity and unit, taxable value, rate and amount of
each tax, total in figures and words, reverse charge, and the signatory.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.template.loader import render_to_string

from apps.core.india import STATE_CODES
from apps.parties.models import Party
from apps.projects.models import Project
from apps.tenants.models import GstRegistration

from ..models import Document, DocumentLine
from .words import rupees_in_words

TITLES = {
    "TAX_INVOICE": "Tax Invoice",
    "BILL_OF_SUPPLY": "Bill of Supply",
    "QUOTATION": "Quotation",
    "PROFORMA": "Proforma Invoice",
    "CREDIT_NOTE": "Credit Note",
    "DEBIT_NOTE": "Debit Note",
}


def inr(amount: Decimal | None) -> str:
    """Indian digit grouping: 3,41,020.00 (lakh / crore commas)."""
    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}.{fraction}"


def _state(code: str | None) -> str:
    return f"{code} - {STATE_CODES.get(code, '')}" if code else ""


def _live_snapshots(doc: Document) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drafts have no frozen snapshots yet: show the current details."""
    from ..services.lifecycle import _party_snapshot, _supplier_snapshot

    registration = GstRegistration.objects.get(pk=doc.gst_registration_id)
    party = Party.objects.get(pk=doc.party_id)
    return _supplier_snapshot(registration), _party_snapshot(party)


def build_context(doc: Document) -> dict[str, Any]:
    if doc.status == "DRAFT":
        supplier, party = _live_snapshots(doc)
    else:
        supplier, party = doc.supplier_snapshot or {}, doc.party_snapshot or {}
    lines = list(DocumentLine.objects.filter(document_id=doc.pk).order_by("line_no"))

    by_rate: dict[Decimal, dict[str, Decimal]] = defaultdict(
        lambda: {"taxable": Decimal(0), "cgst": Decimal(0), "sgst": Decimal(0), "igst": Decimal(0)}
    )
    for ln in lines:
        row = by_rate[ln.gst_rate]
        row["taxable"] += ln.taxable_value
        row["cgst"] += ln.cgst_amount
        row["sgst"] += ln.sgst_amount
        row["igst"] += ln.igst_amount

    original = None
    if doc.original_document_id:
        original = Document.objects.filter(pk=doc.original_document_id).first()
    project = Project.objects.filter(pk=doc.project_id).first() if doc.project_id else None

    deductions = [
        (label, inr(value))
        for label, value in (
            ("Retention", doc.retention_amount),
            ("Income-tax TDS (s.194C)", doc.income_tax_tds_amount),
            ("GST TDS (s.51)", doc.gst_tds_amount),
            ("Mobilisation advance recovered", doc.advance_recovery_amount),
        )
        if value
    ]
    return {
        "title": TITLES.get(doc.doc_type, doc.doc_type),
        "is_draft": doc.status == "DRAFT",
        "is_cancelled": doc.status == "CANCELLED",
        "doc": doc,
        "supplier": supplier,
        "supplier_state": _state(supplier.get("state_code")),
        "party": party,
        "party_state": _state(party.get("state_code")),
        "place_of_supply": _state(doc.place_of_supply),
        "intra_state": doc.supply_type == "INTRA_STATE",
        "project": project,
        "original": original,
        "lines": [
            {
                "no": ln.line_no,
                "description": ln.description,
                "sac_hsn": ln.sac_hsn or "",
                "quantity": f"{ln.quantity.normalize():f}",
                "unit": ln.unit or "",
                "rate": inr(ln.rate),
                "discount": inr(ln.discount_amount) if ln.discount_amount else "",
                "taxable": inr(ln.taxable_value),
                "gst_rate": f"{ln.gst_rate.normalize():f}",
                "total": inr(ln.line_total),
            }
            for ln in lines
        ],
        "tax_summary": [
            {"rate": f"{rate.normalize():f}", **{k: inr(v) for k, v in row.items()}}
            for rate, row in sorted(by_rate.items())
        ],
        "totals": {
            "subtotal": inr(doc.subtotal),
            "cgst": inr(doc.cgst_amount),
            "sgst": inr(doc.sgst_amount),
            "igst": inr(doc.igst_amount),
            "cess": inr(doc.cess_amount) if doc.cess_amount else "",
            "round_off": inr(doc.round_off) if doc.round_off else "",
            "grand_total": inr(doc.grand_total),
            "net_receivable": inr(doc.net_receivable),
        },
        "deductions": deductions,
        "grand_total_words": rupees_in_words(doc.grand_total),
        "net_words": rupees_in_words(doc.net_receivable) if deductions else "",
    }


def render_html(doc: Document) -> str:
    return render_to_string("documents/pdf/document.html", build_context(doc))


def render_pdf(doc: Document) -> bytes:
    from weasyprint import HTML

    pdf: bytes = HTML(string=render_html(doc)).write_pdf()
    return pdf
