"""Reading GSTR-2B as downloaded from the GST portal (Returns, GSTR-2B,
Download, JSON).

The file is {"data": {"gstin", "rtnprd": "MMYYYY", "gendt", "docdata": {...}}}
(some downloads leave out the "data" wrapper). Under docdata, by supplier
("ctin" GSTIN, "trdnm" name):

- b2b / b2ba: invoices ("inv": inum, dt, val, pos, rev, itcavl, rsn, txval,
  igst, cgst, sgst, cess), amendments with the original number (oinum);
- cdnr / cdnra: credit and debit notes ("nt": ntnum, typ "C" / "D", the same
  amounts), amendments with ontnum.

Amounts are either flat on the document or, in older files, per item
("itms": [{"itm_det": {txval, iamt, camt, samt, csamt}}]); both are read.
Dates are dd-mm-yyyy. Other sections (ISD, imports) are counted and left out.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.core.errors import Invalid

MAX_BYTES = 20 * 1024 * 1024
ZERO = Decimal("0.00")
READ = {"b2b": "inv", "b2ba": "inv", "cdnr": "nt", "cdnra": "nt"}


@dataclass
class Doc:
    section: str  # B2B, B2BA, CDNR, CDNRA
    doc_type: str  # INVOICE, CREDIT_NOTE, DEBIT_NOTE
    supplier_gstin: str
    supplier_name: str
    number: str
    original_number: str  # amendments: the number amended
    doc_date: date
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    place_of_supply: str
    reverse_charge: bool
    itc_available: bool
    itc_reason: str

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess


@dataclass
class Return:
    gstin: str
    period: date  # the first of the month
    generated_on: date | None
    docs: list[Doc]
    skipped: dict[str, int] = field(default_factory=dict)  # other sections: how many


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return ZERO


def _date(value: Any) -> date | None:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()  # noqa: DTZ007 - a date only
        except ValueError:
            continue
    return None


def _amounts(doc: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    if "txval" in doc:
        return (
            _money(doc.get("txval")),
            _money(doc.get("igst")),
            _money(doc.get("cgst")),
            _money(doc.get("sgst")),
            _money(doc.get("cess")),
        )
    totals = [ZERO] * 5
    for item in doc.get("itms") or []:
        det = item.get("itm_det") or item
        for i, key in enumerate(("txval", "iamt", "camt", "samt", "csamt")):
            totals[i] += _money(det.get(key))
    return totals[0], totals[1], totals[2], totals[3], totals[4]


def read(data: bytes) -> Return:
    try:
        raw = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Invalid(
            "file", "This is not a GSTR-2B JSON file from the GST portal.", code="not_gstr2b"
        ) from e
    body = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(body, dict) or "docdata" not in body or "rtnprd" not in body:
        raise Invalid(
            "file", "This is not a GSTR-2B JSON file from the GST portal.", code="not_gstr2b"
        )
    period_text = str(body["rtnprd"])
    try:
        period = date(int(period_text[2:]), int(period_text[:2]), 1)
    except ValueError as e:
        raise Invalid(
            "file", "The return period in the file is not readable.", code="not_gstr2b"
        ) from e

    docs: list[Doc] = []
    skipped: dict[str, int] = {}
    for section, entries in (body.get("docdata") or {}).items():
        key = READ.get(section.lower())
        if key is None:
            skipped[section.upper()] = sum(
                len(e.get("inv") or e.get("nt") or [e]) if isinstance(e, dict) else 1
                for e in (entries if isinstance(entries, list) else [entries])
            )
            continue
        for supplier in entries or []:
            gstin = str(supplier.get("ctin") or "").strip().upper()
            name = str(supplier.get("trdnm") or "").strip()
            for doc in supplier.get(key) or []:
                if key == "inv":
                    doc_type = "INVOICE"
                    number, original = doc.get("inum"), doc.get("oinum")
                else:
                    doc_type = "DEBIT_NOTE" if str(doc.get("typ")).upper() == "D" else "CREDIT_NOTE"
                    number, original = doc.get("ntnum"), doc.get("ontnum")
                when = _date(doc.get("dt"))
                if not number or when is None:
                    skipped["UNREADABLE"] = skipped.get("UNREADABLE", 0) + 1
                    continue
                txval, igst, cgst, sgst, cess = _amounts(doc)
                docs.append(
                    Doc(
                        section=section.upper(),
                        doc_type=doc_type,
                        supplier_gstin=gstin,
                        supplier_name=name,
                        number=str(number).strip(),
                        original_number=str(original or "").strip(),
                        doc_date=when,
                        taxable_value=txval,
                        igst=igst,
                        cgst=cgst,
                        sgst=sgst,
                        cess=cess,
                        place_of_supply=str(doc.get("pos") or "").zfill(2)[:2],
                        reverse_charge=str(doc.get("rev") or "N").upper() == "Y",
                        itc_available=str(doc.get("itcavl") or "Y").upper() != "N",
                        itc_reason=str(doc.get("rsn") or "").strip(),
                    )
                )
    return Return(
        gstin=str(body.get("gstin") or "").strip().upper(),
        period=period,
        generated_on=_date(body.get("gendt")) if body.get("gendt") else None,
        docs=docs,
        skipped=skipped,
    )
