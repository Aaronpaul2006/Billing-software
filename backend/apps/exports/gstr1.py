"""GSTR-1 as the GST offline tool's JSON (shape of tool version GST3.2.4).

One GST registration, one month, from the issued tax invoices, credit notes and
debit notes dated in it:

* `b2b` / `cdnr`: recipients with a GSTIN (SEZ: `SEWP` / `SEWOP`);
* `b2cl` / `cdnur`: inter-State invoices to unregistered recipients over
  ₹1,00,000 (and notes on them); `exp`: exports (overseas recipients);
* `b2cs`: every other unregistered supply, netted by supply type, place of
  supply and rate (credit notes subtract, debit notes add);
* `nil`: lines at 0 % (nil-rated, exempt or non-GST: the user checks which);
* `hsn` split into `hsn_b2b` / `hsn_b2c` (returns from May 2025);
* `doc_issue`: numbers issued per series, with the cancelled ones counted.

No official schema could be consulted, so every file carries a warning to
import it into the offline tool and check it before filing. Amounts are
written straight from Decimal (never through float).
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from apps.documents.models import Document, DocumentLine
from apps.tenants.models import GstRegistration

VERSION = "GST3.2.4"
B2CL_LIMIT = Decimal("100000")  # strictly greater; return periods from August 2024
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
GST_TYPES = ("TAX_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE")
DOC_ISSUE = {
    "TAX_INVOICE": (1, "Invoices for outward supply"),
    "DEBIT_NOTE": (4, "Debit Note"),
    "CREDIT_NOTE": (5, "Credit Note"),
}
CHECK_IN_TOOL = (
    "Import this file into the GST offline tool and check it before filing: "
    "the format follows the tool's GSTR-1 JSON (GST3.2.4)."
)

# Unit names people type → the GST portal's unit quantity codes (UQC).
UQC = {
    "NOS": "NOS",
    "NO": "NOS",
    "NUMBER": "NOS",
    "NUMBERS": "NOS",
    "EACH": "NOS",
    "EA": "NOS",
    "PCS": "PCS",
    "PC": "PCS",
    "PIECE": "PCS",
    "PIECES": "PCS",
    "M": "MTR",
    "MTR": "MTR",
    "MTRS": "MTR",
    "METRE": "MTR",
    "METER": "MTR",
    "RMT": "MTR",
    "RM": "MTR",
    "LM": "MTR",
    "SQM": "SQM",
    "M2": "SQM",
    "SQ.M": "SQM",
    "SQMT": "SQM",
    "SQFT": "SQF",
    "SFT": "SQF",
    "SQ.FT": "SQF",
    "SQF": "SQF",
    "CUM": "CBM",
    "M3": "CBM",
    "CU.M": "CBM",
    "CBM": "CBM",
    "CUMT": "CBM",
    "KG": "KGS",
    "KGS": "KGS",
    "KILOGRAM": "KGS",
    "MT": "MTS",
    "MTS": "MTS",
    "TONNE": "TON",
    "TONNES": "TON",
    "TON": "TON",
    "TONS": "TON",
    "QTL": "QTL",
    "QUINTAL": "QTL",
    "BAG": "BAG",
    "BAGS": "BAG",
    "L": "LTR",
    "LTR": "LTR",
    "LITRE": "LTR",
    "LITER": "LTR",
    "BOX": "BOX",
    "BOXES": "BOX",
    "SET": "SET",
    "SETS": "SET",
    "ROLL": "ROL",
    "ROLLS": "ROL",
    "BUNDLE": "BDL",
    "BDL": "BDL",
    "DOZEN": "DOZ",
    "DOZ": "DOZ",
    "PAIR": "PRS",
    "PRS": "PRS",
    "GM": "GMS",
    "GMS": "GMS",
    "GRAM": "GMS",
    "KM": "KME",
    "CFT": "OTH",
    "LS": "OTH",
    "LUMPSUM": "OTH",
    "JOB": "OTH",
}


class Gstr1Error(Exception):
    """The return cannot be made (e.g. the registration does not file GSTR-1)."""


# --- JSON with exact decimals ---------------------------------------------------------


class Num:
    """A number written to JSON exactly as given (amounts with 2 decimals)."""

    def __init__(self, text: str) -> None:
        self.text = text


def amount(value: Decimal) -> Num:
    return Num(f"{value.quantize(CENT, ROUND_HALF_UP):.2f}")


def rate(value: Decimal) -> Num:
    text = format(value.normalize(), "f")
    return Num(text)


def dumps(value: Any) -> str:
    if isinstance(value, Num):
        return value.text
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(k)}:{dumps(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(dumps(v) for v in value) + "]"
    if isinstance(value, Decimal):
        raise TypeError("wrap Decimal in amount() or rate()")
    return json.dumps(value, ensure_ascii=False)


# --- the return -------------------------------------------------------------------------


@dataclass
class Taxes:
    txval: Decimal = ZERO
    iamt: Decimal = ZERO
    camt: Decimal = ZERO
    samt: Decimal = ZERO
    csamt: Decimal = ZERO
    qty: Decimal = Decimal("0")

    def add(self, line: DocumentLine, sign: int = 1, qty: Decimal = Decimal("0")) -> None:
        self.txval += sign * line.taxable_value
        self.iamt += sign * line.igst_amount
        self.camt += sign * line.cgst_amount
        self.samt += sign * line.sgst_amount
        self.csamt += sign * line.cess_amount
        self.qty += sign * qty

    def item(self, rt: Decimal, inter: bool) -> dict[str, Any]:
        out: dict[str, Any] = {"txval": amount(self.txval), "rt": rate(rt)}
        if inter:
            out["iamt"] = amount(self.iamt)
        else:
            out["camt"] = amount(self.camt)
            out["samt"] = amount(self.samt)
        out["csamt"] = amount(self.csamt)
        return out


@dataclass
class Return:
    warnings: list[str] = field(default_factory=lambda: [CHECK_IN_TOOL])

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)


def _idt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _items(lines: list[DocumentLine], inter: bool, *, nested: bool = True) -> list[dict[str, Any]]:
    by_rate: dict[Decimal, Taxes] = defaultdict(Taxes)
    for line in lines:
        by_rate[line.gst_rate].add(line)
    items = []
    for rt in sorted(by_rate):
        detail = by_rate[rt].item(rt, inter)
        num = int(rt * 100) + 1  # the offline tool's item number: 18 % → 1801
        items.append({"num": num, "itm_det": detail} if nested else detail)
    return items


def _uqc(line: DocumentLine, ret: Return) -> tuple[str, Decimal]:
    if (line.sac_hsn or "").startswith("99"):
        return "NA", Decimal("0")  # services: no quantity
    unit = (line.unit or "").strip().upper().rstrip(".")
    code = UQC.get(unit)
    if code is None:
        ret.warn(f"Unit '{line.unit or ''}' has no GST unit code (UQC); it is reported as OTH.")
        code = "OTH"
    return code, line.quantity


def _is_b2cl(doc: Document) -> bool:
    """Inter-State, unregistered, invoice value over the limit; a note follows
    the invoice it adjusts."""
    if doc.supply_type != "INTER_STATE":
        return False
    invoice = doc if doc.doc_type == "TAX_INVOICE" else doc.original_document
    return invoice is not None and invoice.grand_total > B2CL_LIMIT


def build_gstr1(tenant_id: uuid.UUID, params: dict[str, Any]) -> tuple[bytes, str, int, list[str]]:
    registration = GstRegistration.objects.filter(pk=params["gst_registration_id"]).first()
    if (
        registration is None
        or registration.registration_type != "REGULAR"
        or not registration.gstin
    ):
        raise Gstr1Error("Only regular GST registrations file GSTR-1.")
    year, month = (int(x) for x in params["period"].split("-"))
    start = date(year, month, 1)
    end = date(year + month // 12, month % 12 + 1, 1)
    documents = list(
        Document.objects.filter(
            gst_registration_id=registration.pk,
            doc_type__in=GST_TYPES,
            doc_date__gte=start,
            doc_date__lt=end,
        )
        .exclude(status="DRAFT")
        .select_related("original_document")
        .order_by("issued_at", "doc_number")
    )
    lines: dict[uuid.UUID, list[DocumentLine]] = defaultdict(list)
    for line in DocumentLine.objects.filter(document__in=[d.pk for d in documents]).order_by(
        "document_id", "line_no"
    ):
        lines[line.document_id].append(line)

    ret = Return()
    b2b: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cdnr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    b2cl: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cdnur: list[dict[str, Any]] = []
    exp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    b2cs: dict[tuple[str, str, Decimal], Taxes] = defaultdict(Taxes)
    nil: dict[str, Decimal] = defaultdict(Decimal)
    hsn: dict[str, dict[tuple[str, Decimal, str], Taxes]] = {
        "b2b": defaultdict(Taxes),
        "b2c": defaultdict(Taxes),
    }
    counted = 0

    for doc in documents:
        if doc.status == "CANCELLED":
            continue
        counted += 1
        party = doc.party_snapshot or {}
        treatment = party.get("gst_treatment")
        gstin = str(party.get("gstin") or "")
        inter = doc.supply_type == "INTER_STATE"
        note = doc.doc_type != "TAX_INVOICE"
        all_lines = lines[doc.pk]
        taxed = [ln for ln in all_lines if ln.gst_rate > 0]
        nil_lines = [ln for ln in all_lines if ln.gst_rate == 0]
        sign = -1 if doc.doc_type == "CREDIT_NOTE" else 1

        if doc.supply_category == "EXPORT":
            section, bucket = "exp", "b2c"
        elif gstin and treatment in ("REGISTERED", "COMPOSITION", "SEZ"):
            section, bucket = "b2b", "b2b"
        elif _is_b2cl(doc):
            section, bucket = "b2cl", "b2c"
        else:
            section, bucket = "b2cs", "b2c"
        if doc.supply_category == "SEZ" and not gstin:
            ret.warn(f"{doc.doc_number}: SEZ recipient without a GSTIN is reported as B2C.")

        inv_typ = "R"
        if doc.supply_category == "SEZ":
            inv_typ = "SEWOP" if doc.lut else "SEWP"

        if section == "b2b" and taxed:
            if note:
                cdnr[gstin].append(
                    {
                        "ntty": "C" if doc.doc_type == "CREDIT_NOTE" else "D",
                        "nt_num": doc.doc_number,
                        "nt_dt": _idt(doc.doc_date),
                        "val": amount(doc.grand_total),
                        "pos": doc.place_of_supply,
                        "rchrg": "Y" if doc.reverse_charge else "N",
                        "inv_typ": inv_typ,
                        "itms": _items(taxed, inter),
                    }
                )
            else:
                b2b[gstin].append(
                    {
                        "inum": doc.doc_number,
                        "idt": _idt(doc.doc_date),
                        "val": amount(doc.grand_total),
                        "pos": doc.place_of_supply,
                        "rchrg": "Y" if doc.reverse_charge else "N",
                        "inv_typ": inv_typ,
                        "itms": _items(taxed, inter),
                    }
                )
        elif section == "b2cl" and taxed:
            if note:
                cdnur.append(
                    {
                        "ntty": "C" if doc.doc_type == "CREDIT_NOTE" else "D",
                        "nt_num": doc.doc_number,
                        "nt_dt": _idt(doc.doc_date),
                        "val": amount(doc.grand_total),
                        "typ": "B2CL",
                        "pos": doc.place_of_supply,
                        "itms": _items(taxed, inter),
                    }
                )
            else:
                b2cl[doc.place_of_supply].append(
                    {
                        "inum": doc.doc_number,
                        "idt": _idt(doc.doc_date),
                        "val": amount(doc.grand_total),
                        "itms": _items(taxed, inter),
                    }
                )
        elif section == "exp" and (taxed or nil_lines):
            typ = "WOPAY" if doc.lut else "WPAY"
            if note:
                cdnur.append(
                    {
                        "ntty": "C" if doc.doc_type == "CREDIT_NOTE" else "D",
                        "nt_num": doc.doc_number,
                        "nt_dt": _idt(doc.doc_date),
                        "val": amount(doc.grand_total),
                        "typ": "EXPWP" if typ == "WPAY" else "EXPWOP",
                        "itms": _items(all_lines, True),
                    }
                )
            else:
                exp[typ].append(
                    {
                        "inum": doc.doc_number,
                        "idt": _idt(doc.doc_date),
                        "val": amount(doc.grand_total),
                        "itms": _items(all_lines, True, nested=False),
                    }
                )
            ret.warn(
                "Exports: add the shipping bill number, date and port code in the offline tool."
            )
            nil_lines = []  # zero-rated exports belong in the export table, not in Table 8
        elif section == "b2cs":
            for line in taxed:
                b2cs[("INTER" if inter else "INTRA", doc.place_of_supply, line.gst_rate)].add(
                    line, sign
                )

        for line in nil_lines:
            kind = ("INTR" if inter else "INTRA") + ("B2B" if section == "b2b" else "B2C")
            nil[kind] += sign * line.taxable_value
        if nil_lines:
            ret.warn(
                "Lines at 0 % GST are reported as nil-rated (Table 8): change them to exempt "
                "or non-GST in the offline tool where that is what they are."
            )

        # HSN summary (Table 12): every line, nil-rated ones at rate 0.
        for line in all_lines:
            if not line.sac_hsn:
                ret.warn(
                    f"{doc.doc_number}: a line without an HSN / SAC code is left out of "
                    "the HSN summary."
                )
                continue
            uqc, qty = _uqc(line, ret)
            hsn[bucket][(line.sac_hsn, line.gst_rate, uqc)].add(line, sign, qty)

    out: dict[str, Any] = {
        "gstin": registration.gstin,
        "fp": f"{month:02d}{year}",
        "version": VERSION,
        "hash": "hash",
    }
    if b2b:
        out["b2b"] = [{"ctin": ctin, "inv": inv} for ctin, inv in sorted(b2b.items())]
    if b2cl:
        out["b2cl"] = [{"pos": pos, "inv": inv} for pos, inv in sorted(b2cl.items())]
    if b2cs:
        rows = []
        for (sply_ty, pos, rt), taxes in sorted(b2cs.items()):
            row: dict[str, Any] = {
                "sply_ty": sply_ty,
                "pos": pos,
                "typ": "OE",
                **taxes.item(rt, sply_ty == "INTER"),
            }
            if taxes.txval < 0:
                ret.warn(
                    "A B2C (small) row is negative after credit notes: "
                    "check it in the offline tool."
                )
            rows.append(row)
        out["b2cs"] = rows
    if exp:
        out["exp"] = [{"exp_typ": typ, "inv": inv} for typ, inv in sorted(exp.items())]
    if cdnr:
        out["cdnr"] = [{"ctin": ctin, "nt": nt} for ctin, nt in sorted(cdnr.items())]
    if cdnur:
        out["cdnur"] = cdnur
    if nil:
        out["nil"] = {
            "inv": [
                {
                    "sply_ty": kind,
                    "expt_amt": amount(ZERO),
                    "nil_amt": amount(value),
                    "ngsup_amt": amount(ZERO),
                }
                for kind, value in sorted(nil.items())
            ]
        }
    doc_det = _doc_issue(documents)
    if doc_det:
        out["doc_issue"] = {"doc_det": doc_det}
    hsn_out: dict[str, Any] = {}
    for bucket in ("b2b", "b2c"):
        rows = []
        for i, ((code, rt, uqc), taxes) in enumerate(sorted(hsn[bucket].items()), start=1):
            if taxes.txval < 0:
                ret.warn(
                    f"HSN {code} is negative after credit notes: "
                    "the portal refuses negative HSN rows."
                )
            if bucket == "b2b" and len(code) < 6:
                ret.warn(
                    "Businesses with turnover over ₹5 crore must give 6-digit HSN / SAC codes "
                    "for B2B supplies."
                )
            rows.append(
                {
                    "num": i,
                    "hsn_sc": code,
                    "uqc": uqc,
                    "qty": amount(taxes.qty),
                    "rt": rate(rt),
                    "txval": amount(taxes.txval),
                    "iamt": amount(taxes.iamt),
                    "camt": amount(taxes.camt),
                    "samt": amount(taxes.samt),
                    "csamt": amount(taxes.csamt),
                }
            )
        if rows:
            hsn_out[f"hsn_{bucket}"] = rows
    if hsn_out:
        out["hsn"] = hsn_out

    body = dumps(out).encode("utf-8")
    if len(body) > 4.7 * 1024 * 1024:
        ret.warn("The file is over the offline tool's 5 MB limit: split the month in the tool.")
    name = f"gstr1_{registration.gstin}_{month:02d}{year}.json"
    return body, name, counted, ret.warnings


def _doc_issue(documents: list[Document]) -> list[dict[str, Any]]:
    """Table 13: per type and series, the first and last number and how many
    were cancelled. Numbers are gapless per series, so the count is exact."""
    by_series: dict[tuple[str, uuid.UUID | None], list[Document]] = defaultdict(list)
    for doc in documents:
        by_series[(doc.doc_type, doc.series_id)].append(doc)
    out = []
    for doc_type in ("TAX_INVOICE", "DEBIT_NOTE", "CREDIT_NOTE"):
        docs_rows: list[dict[str, Any]] = []
        for (kind, _), docs in by_series.items():
            if kind != doc_type:
                continue
            ordered = sorted(docs, key=lambda d: (d.issued_at or d.created_at, d.doc_number or ""))
            cancelled = sum(1 for d in ordered if d.status == "CANCELLED")
            docs_rows.append(
                {
                    "num": len(docs_rows) + 1,
                    "from": ordered[0].doc_number,
                    "to": ordered[-1].doc_number,
                    "totnum": len(ordered),
                    "cancel": cancelled,
                    "net_issue": len(ordered) - cancelled,
                }
            )
        if docs_rows:
            number, label = DOC_ISSUE[doc_type]
            out.append({"doc_num": number, "doc_typ": label, "docs": docs_rows})
    return out
