"""Document PDFs: build the context, render HTML (auto-escaped Django
template, no user-controlled template content), convert with WeasyPrint.

The layout carries the tax-invoice particulars of CGST Rule 46: supplier and
recipient names, addresses and GSTINs, number and date, place of supply with
state name, HSN/SAC, quantity and unit, taxable value, rate and amount of
each tax, total in figures and words, reverse charge, and the signatory.
"""

import base64
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import segno
from django.template.loader import render_to_string

from apps.core.india import place_name
from apps.files import storage
from apps.files.models import Attachment
from apps.parties.models import Party
from apps.projects.models import BoqItem, Project
from apps.tenants import printing
from apps.tenants.models import GstRegistration

from ..models import Document, DocumentLine, DocumentLineMeasurement
from .words import rupees_in_words

log = logging.getLogger(__name__)

# Bills that ask to be paid: they carry the bank details and the UPI QR code.
PAYABLE = frozenset({"TAX_INVOICE", "BILL_OF_SUPPLY", "DEBIT_NOTE", "PROFORMA"})
COPIES = ("original", "duplicate", "triplicate")
BANK_FIELDS = ("bank_account_name", "bank_name", "bank_account_number", "bank_ifsc", "bank_branch")

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


def _qty(value: Decimal | None) -> str:
    return "" if value is None else f"{value.normalize():f}"


def _state(code: str | None) -> str:
    return f"{code} - {place_name(code)}" if code else ""


# CGST Rules r.46(1)(p) and the IGST zero-rating conditions: the words these
# invoices must carry.
DECLARATIONS = {
    ("SEZ", True): "SUPPLY TO SEZ UNIT OR SEZ DEVELOPER FOR AUTHORISED OPERATIONS UNDER BOND"
    " OR LETTER OF UNDERTAKING WITHOUT PAYMENT OF INTEGRATED TAX",
    ("SEZ", False): "SUPPLY TO SEZ UNIT OR SEZ DEVELOPER FOR AUTHORISED OPERATIONS ON PAYMENT"
    " OF INTEGRATED TAX",
    ("EXPORT", True): "SUPPLY MEANT FOR EXPORT UNDER BOND OR LETTER OF UNDERTAKING WITHOUT"
    " PAYMENT OF INTEGRATED TAX",
    ("EXPORT", False): "SUPPLY MEANT FOR EXPORT ON PAYMENT OF INTEGRATED TAX",
}


def _declaration(doc: Document, supplier: dict[str, Any]) -> str | None:
    if doc.reverse_charge:
        return "Tax on this supply is payable by the recipient under reverse charge."
    text = DECLARATIONS.get((doc.supply_category, doc.lut))
    if text and doc.lut and supplier.get("lut_arn"):
        text += f" (LUT ARN {supplier['lut_arn']})"
    return text


def _live_snapshots(doc: Document) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drafts have no frozen snapshots yet: show the current details."""
    from ..services.lifecycle import _party_snapshot, _supplier_snapshot

    registration = GstRegistration.objects.get(pk=doc.gst_registration_id)
    party = Party.objects.get(pk=doc.party_id)
    return _supplier_snapshot(registration, lut=doc.lut), _party_snapshot(party)


def copy_label(copy: str | None, lines: list[DocumentLine]) -> str:
    """CGST Rules r.48: goods in triplicate (the duplicate travels with the
    transporter), services in duplicate (the duplicate is the supplier's)."""
    if copy is None:
        return ""
    goods = any(ln.sac_hsn and not ln.sac_hsn.startswith("99") for ln in lines)
    return {
        "original": "Original for recipient",
        "duplicate": "Duplicate for transporter" if goods else "Duplicate for supplier",
        "triplicate": "Triplicate for supplier",
    }[copy]


def _image(attachment_id: str | None) -> str | None:
    """A logo or signature as a data: URL (the PDF renderer fetches nothing).
    A missing or unreadable image leaves a gap rather than failing the bill."""
    if not attachment_id:
        return None
    a = Attachment.objects.filter(pk=attachment_id, status="AVAILABLE").first()
    if a is None or a.content_type not in printing.IMAGE_TYPES:
        return None
    try:
        data = storage.get(a.storage_key)
    except Exception:
        log.warning("print image %s could not be read", attachment_id, exc_info=True)
        return None
    return f"data:{a.content_type};base64,{base64.b64encode(data).decode()}"


def _site_photos(doc: Document) -> list[dict[str, Any]]:
    """Proof of work: the diary photos chosen for this bill, as data: URLs,
    with their day and caption. A photo that cannot be read is left out."""
    from apps.diary.models import DocumentPhoto  # the diary builds on documents

    rows = (
        DocumentPhoto.objects.filter(document_id=doc.pk)
        .select_related("diary_photo__entry", "diary_photo__attachment")
        .order_by("sort_order")
    )
    out = []
    for row in rows:
        photo = row.diary_photo
        a = photo.attachment
        if a.status != "AVAILABLE" or a.content_type not in printing.IMAGE_TYPES:
            continue
        try:
            data = storage.get(a.storage_key)
        except Exception:
            log.warning("site photo %s could not be read", a.pk, exc_info=True)
            continue
        out.append(
            {
                "src": f"data:{a.content_type};base64,{base64.b64encode(data).decode()}",
                "caption": photo.caption or "",
                "date": f"{photo.entry.entry_date:%d %b %Y}".lstrip("0"),
            }
        )
    return out


def upi_link(upi_id: str, payee: str, amount: Decimal, note: str) -> str:
    """upi://pay with the exact amount: any UPI app fills in the payment."""
    query = urlencode(
        {"pa": upi_id, "pn": payee[:50], "am": f"{amount:.2f}", "cu": "INR", "tn": note},
        quote_via=quote,
    )
    return f"upi://pay?{query}"


def _payment(doc: Document, supplier: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    bank = {k: settings.get(k) for k in BANK_FIELDS}
    asks = doc.doc_type in PAYABLE and doc.status != "CANCELLED"
    upi = settings.get("upi_id")
    qr = None
    if asks and upi and doc.status != "DRAFT" and doc.net_receivable > 0:
        payee = supplier.get("trade_name") or supplier.get("legal_name") or ""
        link = upi_link(upi, payee, doc.net_receivable, doc.doc_number or "")
        qr = segno.make(link, error="m").svg_data_uri(scale=3, border=1)
    return {
        "bank": bank if asks and any(bank.values()) else None,
        "upi_id": upi if asks else None,
        "upi_qr": qr,
        "upi_amount": inr(doc.net_receivable),
    }


def build_context(doc: Document, copy: str | None = None) -> dict[str, Any]:
    if doc.status == "DRAFT":
        supplier, party = _live_snapshots(doc)
    else:
        supplier, party = doc.supplier_snapshot or {}, doc.party_snapshot or {}
    # frozen at issue (B.13); drafts and bills issued before then: the current settings
    settings = supplier.get("print") or printing.snapshot(doc.tenant_id)
    lines = list(DocumentLine.objects.filter(document_id=doc.pk).order_by("line_no"))
    measured: dict[Any, list[DocumentLineMeasurement]] = {ln.pk: [] for ln in lines}
    for m in DocumentLineMeasurement.objects.filter(document_id=doc.pk).order_by("row_no"):
        measured[m.line_id].append(m)

    # HSN / SAC summary: one row per code and rate
    by_hsn: dict[tuple[str, Decimal], dict[str, Decimal]] = defaultdict(
        lambda: {"taxable": Decimal(0), "cgst": Decimal(0), "sgst": Decimal(0), "igst": Decimal(0)}
    )
    for ln in lines:
        row = by_hsn[(ln.sac_hsn or "", ln.gst_rate)]
        row["taxable"] += ln.taxable_value
        row["cgst"] += ln.cgst_amount
        row["sgst"] += ln.sgst_amount
        row["igst"] += ln.igst_amount

    original = None
    if doc.original_document_id:
        original = Document.objects.filter(pk=doc.original_document_id).first()
    project = Project.objects.filter(pk=doc.project_id).first() if doc.project_id else None
    boq_codes = dict(
        BoqItem.objects.filter(
            pk__in=[ln.boq_item_id for ln in lines if ln.boq_item_id]
        ).values_list("id", "item_code")
    )

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
        "detailed": settings.get("layout", "DETAILED") != "SIMPLE",
        "copy_label": copy_label(copy, lines),
        "logo": _image(settings.get("logo_attachment_id")),
        "signature": _image(settings.get("signature_attachment_id")),
        "site_photos": _site_photos(doc) if doc.project_id else [],
        **_payment(doc, supplier, settings),
        "ra_sequence": doc.ra_sequence if doc.is_ra_bill else None,
        "show_discount": any(ln.discount_amount for ln in lines),
        "is_draft": doc.status == "DRAFT",
        "is_cancelled": doc.status == "CANCELLED",
        "declaration": _declaration(doc, supplier),
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
                "item_code": boq_codes.get(ln.boq_item_id, ""),
                "quantity": _qty(ln.quantity),
                "previous": _qty(ln.prev_cumulative_qty),
                "up_to_date": _qty(
                    None if ln.prev_cumulative_qty is None else ln.prev_cumulative_qty + ln.quantity
                ),
                "unit": ln.unit or "",
                "rate": inr(ln.rate),
                "discount": inr(ln.discount_amount) if ln.discount_amount else "",
                "taxable": inr(ln.taxable_value),
                "gst_rate": f"{ln.gst_rate.normalize():f}",
                "total": inr(ln.line_total),
                # B.9: the measurement sheet, printed under the line
                "measurements": [
                    {
                        "description": m.description or "",
                        "sizes": " \u00d7 ".join(  # the multiplication sign
                            _qty(v) for v in (m.nos, m.length, m.breadth, m.height) if v is not None
                        ),
                        "quantity": ("less " if m.deduct else "") + _qty(m.quantity),
                    }
                    for m in measured[ln.pk]
                ],
            }
            for ln in lines
        ],
        "hsn_summary": [
            {
                "hsn": hsn,
                "rate": f"{rate.normalize():f}",
                **{k: inr(v) for k, v in row.items()},
                "tax": inr(row["cgst"] + row["sgst"] + row["igst"]),
            }
            for (hsn, rate), row in sorted(by_hsn.items())
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


def render_html(doc: Document, copy: str | None = None) -> str:
    return render_to_string("documents/pdf/document.html", build_context(doc, copy))


def render_pdf(doc: Document, copy: str | None = None) -> bytes:
    from weasyprint import HTML

    pdf: bytes = HTML(string=render_html(doc, copy)).write_pdf()
    return pdf
