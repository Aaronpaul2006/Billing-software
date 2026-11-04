"""Vouchers for Tally (B.16): one XML file to import with Gateway of Tally,
Import, Transactions.

Accounting-voucher view (no stock items), one TALLYMESSAGE per voucher:

- Sales (tax invoice, bill of supply) and Debit Note: Dr client (what the
  client pays now, a New Ref bill under our number), Dr TDS / GST TDS /
  retention / advance recovered; Cr sales (taxable value), CGST / SGST /
  IGST / cess (when charged: not under reverse charge), round off.
- Credit Note: the same, the other way round, against the original bill.
- Receipt: Dr bank (cash for cash payments), Cr client, settled against each
  bill it paid (Agst Ref), the rest On Account.

Tally conventions: a debit is ISDEEMEDPOSITIVE Yes with a negative amount, a
credit No with a positive one; every voucher adds up to zero; dates are
YYYYMMDD. Ledgers are matched by name, so they must exist in Tally first:
the file lists the ones it uses. REMOTEID is our id, so a voucher is the
same voucher on every export. Non-ASCII characters are written as character
references, which every Tally version reads.
"""

import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.india import place_name
from apps.documents.models import Document
from apps.parties.models import Party
from apps.payments.models import Allocation, Payment
from apps.tenants import tally

from .builders import TooManyRows

MAX_VOUCHERS = 20_000
ZERO = Decimal("0.00")
SALES_TYPES = ("TAX_INVOICE", "BILL_OF_SUPPLY")
VOUCHER_TYPES = {
    "TAX_INVOICE": "Sales",
    "BILL_OF_SUPPLY": "Sales",
    "DEBIT_NOTE": "Debit Note",
    "CREDIT_NOTE": "Credit Note",
}
TITLES = {
    "TAX_INVOICE": "Tax invoice",
    "BILL_OF_SUPPLY": "Bill of supply",
    "DEBIT_NOTE": "Debit note",
    "CREDIT_NOTE": "Credit note",
}


@dataclass(frozen=True)
class Entry:
    ledger: str
    debit: Decimal  # positive: debit; negative: credit
    party: bool = False
    bills: tuple[tuple[str, str, Decimal], ...] = ()  # (name, Tally bill type, debit)


def _amount(debit: Decimal) -> str:
    """Tally's sign: debits negative."""
    return f"{-debit:.2f}"


def _sub(parent: ET.Element, tag: str, text: str | None) -> None:
    if text:
        ET.SubElement(parent, tag).text = text


def _voucher(
    *,
    remote_id: uuid.UUID,
    vch_type: str,
    on: date,
    number: str | None,
    party: str,
    narration: str,
    entries: list[Entry],
    extra: dict[str, str | None] | None = None,
) -> ET.Element:
    total = sum((e.debit for e in entries), ZERO)
    if total != ZERO:  # never write a voucher Tally would refuse
        raise ValueError(f"voucher {number} does not balance: {total}")
    message = ET.Element("TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
    v = ET.SubElement(
        message,
        "VOUCHER",
        {
            "REMOTEID": str(remote_id),
            "VCHTYPE": vch_type,
            "ACTION": "Create",
            "OBJVIEW": "Accounting Voucher View",
        },
    )
    _sub(v, "DATE", on.strftime("%Y%m%d"))
    _sub(v, "VOUCHERTYPENAME", vch_type)
    _sub(v, "VOUCHERNUMBER", number)
    _sub(v, "REFERENCE", number)
    _sub(v, "PARTYLEDGERNAME", party)
    for tag, value in (extra or {}).items():
        _sub(v, tag, value)
    _sub(v, "NARRATION", narration)
    _sub(v, "PERSISTEDVIEW", "Accounting Voucher View")
    _sub(v, "ISINVOICE", "No")
    for e in entries:
        if e.debit == ZERO:
            continue
        row = ET.SubElement(v, "ALLLEDGERENTRIES.LIST")
        _sub(row, "LEDGERNAME", e.ledger)
        _sub(row, "ISDEEMEDPOSITIVE", "Yes" if e.debit > 0 else "No")
        _sub(row, "ISPARTYLEDGER", "Yes" if e.party else "No")
        _sub(row, "AMOUNT", _amount(e.debit))
        for name, bill_type, debit in e.bills:
            bill = ET.SubElement(row, "BILLALLOCATIONS.LIST")
            _sub(bill, "NAME", name)
            _sub(bill, "BILLTYPE", bill_type)
            _sub(bill, "AMOUNT", _amount(debit))
    return message


def _document_entries(
    doc: Document, client: str, ledgers: dict[str, str], against: str | None
) -> tuple[list[Entry], list[str]]:
    """Entries of a sales-side document as for a sale (debits positive)."""
    warnings: list[str] = []
    taxes = [
        (ledgers["cgst_ledger"], doc.cgst_amount),
        (ledgers["sgst_ledger"], doc.sgst_amount),
        (ledgers["igst_ledger"], doc.igst_amount),
        (ledgers["cess_ledger"], doc.cess_amount),
    ]
    charged = doc.grand_total - doc.subtotal - doc.round_off  # the tax in the total
    if charged != sum((t for _, t in taxes), ZERO):
        if charged != ZERO:
            raise ValueError(f"{doc.doc_number}: tax in the total does not match its lines")
        taxes = []  # reverse charge: the client pays the tax to the government
        warnings.append(f"{doc.doc_number}: reverse charge, so no output tax is posted.")
    deductions = [
        (ledgers["tds_ledger"], doc.income_tax_tds_amount),
        (ledgers["gst_tds_ledger"], doc.gst_tds_amount),
        (ledgers["retention_ledger"], doc.retention_amount),
        (ledgers["advance_ledger"], doc.advance_recovery_amount),
    ]
    bill = (against, "Agst Ref") if against else (doc.doc_number or "", "New Ref")
    entries = [
        Entry(client, doc.net_receivable, party=True, bills=((*bill, doc.net_receivable),)),
        *(Entry(name, amount) for name, amount in deductions),
        Entry(ledgers["sales_ledger"], -doc.subtotal),
        *(Entry(name, -amount) for name, amount in taxes),
        Entry(ledgers["round_off_ledger"], -doc.round_off),
    ]
    return entries, warnings


def _flip(entries: list[Entry]) -> list[Entry]:
    return [
        Entry(e.ledger, -e.debit, e.party, tuple((n, t, -a) for n, t, a in e.bills))
        for e in entries
    ]


def _payment_entries(
    payment: Payment, client: str, ledgers: dict[str, str], bills: list[tuple[str, Decimal]]
) -> list[Entry]:
    bank = ledgers["cash_ledger"] if payment.mode == "CASH" else ledgers["bank_ledger"]
    settled = sum((a for _, a in bills), ZERO)
    refs = [(name, "Agst Ref", -amount) for name, amount in bills]
    if payment.amount > settled:
        refs.append(("On Account", "On Account", -(payment.amount - settled)))
    return [
        Entry(bank, payment.amount),
        Entry(client, -payment.amount, party=True, bills=tuple(refs)),
    ]


def _envelope(messages: list[ET.Element]) -> bytes:
    root = ET.Element("ENVELOPE")
    header = ET.SubElement(root, "HEADER")
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
    data = ET.SubElement(ET.SubElement(root, "BODY"), "IMPORTDATA")
    desc = ET.SubElement(data, "REQUESTDESC")
    ET.SubElement(desc, "REPORTNAME").text = "Vouchers"
    request = ET.SubElement(data, "REQUESTDATA")
    request.extend(messages)
    ET.indent(root)
    body: bytes = ET.tostring(root, encoding="us-ascii", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + body + b"\n"


def build_tally(tenant_id: uuid.UUID, params: dict[str, Any]) -> tuple[bytes, str, int, list[str]]:
    """(file, name, voucher count, warnings). Call inside tenant_context."""
    start, end = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
    ledgers = tally.ledgers(tenant_id)
    docs = list(
        Document.objects.filter(
            doc_type__in=VOUCHER_TYPES, doc_date__range=(start, end), status="ISSUED"
        ).order_by("doc_date", "doc_number")
    )
    payments = list(
        Payment.objects.filter(payment_date__range=(start, end), status="RECORDED").order_by(
            "payment_date", "id"
        )
    )
    if len(docs) + len(payments) > MAX_VOUCHERS:
        raise TooManyRows(f"More than {MAX_VOUCHERS:,} vouchers: choose a shorter period.")
    party_ids = {d.party_id for d in docs} | {p.party_id for p in payments}
    clients = dict(Party.objects.filter(pk__in=party_ids).values_list("id", "display_name"))
    originals = dict(
        Document.objects.filter(
            pk__in=[d.original_document_id for d in docs if d.original_document_id]
        ).values_list("id", "doc_number")
    )
    paid: dict[Any, list[tuple[str, Decimal]]] = defaultdict(list)
    for payment_id, number, amount in Allocation.objects.filter(
        payment_id__in=[p.pk for p in payments], document__isnull=False
    ).values_list("payment_id", "document__doc_number", "amount"):
        paid[payment_id].append((number, amount))

    messages: list[ET.Element] = []
    warnings: list[str] = []
    used: set[str] = set()
    for d in docs:
        client = str(clients[d.party_id])
        against = originals.get(d.original_document_id) if d.doc_type == "CREDIT_NOTE" else None
        entries, notes = _document_entries(d, client, ledgers, against)
        warnings += notes
        if d.doc_type == "CREDIT_NOTE":
            entries = _flip(entries)
        used.update(e.ledger for e in entries if e.debit != ZERO)
        snapshot = d.party_snapshot or {}
        messages.append(
            _voucher(
                remote_id=d.pk,
                vch_type=VOUCHER_TYPES[d.doc_type],
                on=d.doc_date,
                number=d.doc_number,
                party=client,
                narration=f"{TITLES[d.doc_type]} {d.doc_number}",
                entries=entries,
                extra={
                    "PARTYGSTIN": snapshot.get("gstin"),
                    "PLACEOFSUPPLY": place_name(d.place_of_supply),
                },
            )
        )
    for p in payments:
        client = str(clients[p.party_id])
        entries = _payment_entries(p, client, ledgers, paid[p.pk])
        used.update(e.ledger for e in entries)
        how = " ".join(x for x in (p.mode.replace("_", " ").lower(), p.reference) if x)
        messages.append(
            _voucher(
                remote_id=p.pk,
                vch_type="Receipt",
                on=p.payment_date,
                number=None,  # Tally numbers its own receipts
                party=client,
                narration=f"Payment received ({how})",
                entries=entries,
            )
        )

    cancelled = Document.objects.filter(
        doc_type__in=VOUCHER_TYPES, doc_date__range=(start, end), status="CANCELLED"
    ).count()
    voided = Payment.objects.filter(payment_date__range=(start, end), status="VOIDED").count()
    if cancelled:
        warnings.append(
            f"{cancelled} cancelled bill(s) left out; if one was imported before, cancel it in"
            " Tally too."
        )
    if voided:
        warnings.append(f"{voided} voided payment(s) left out.")
    if messages:
        warnings.append(
            "Create these ledgers in Tally before importing (names must match): "
            + ", ".join(sorted(used))
            + "."
        )
    name = f"tally-vouchers-{start.isoformat()}-to-{end.isoformat()}.xml"
    return _envelope(messages), name, len(messages), warnings
