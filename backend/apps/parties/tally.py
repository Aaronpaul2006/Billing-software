"""Reading masters from Tally (Part B): clients, vendors and stock items.

The file is what Tally exports as XML (Data Interchange): Gateway of Tally,
Export, Masters (TallyPrime), or Display, List of Accounts, Alt+E
(Tally.ERP 9). Both put each master in a TALLYMESSAGE:

- GROUP: the account groups, to follow a ledger's group up to Sundry Debtors
  (clients) or Sundry Creditors (vendors). Other ledgers (bank, sales, taxes)
  are counted and left alone.
- LEDGER: name, GST registration (PARTYGSTIN and GSTREGISTRATIONTYPE on
  Tally.ERP 9 and early TallyPrime; LEDGSTREGDETAILS.LIST from TallyPrime 3),
  state, PAN (INCOMETAXNUMBER), email, phone, address and PIN code (on the
  ledger, or in LEDMAILINGDETAILS.LIST from TallyPrime 3), mailing name,
  credit period ("30 Days").
- STOCKITEM: name, base unit, description, HSN, the integrated tax rate (the
  latest GSTDETAILS.LIST; HSNDETAILS.LIST from TallyPrime 3), selling price
  (the latest STANDARDPRICELIST.LIST, "380.00/Bag").

Tally writes UTF-8 or UTF-16 and, now and then, character references XML
does not allow (&#4; for "Primary"); those are dropped. defusedxml refuses
entity tricks.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from apps.core.errors import Invalid

MAX_BYTES = 20 * 1024 * 1024
DEBTORS, CREDITORS = "sundry debtors", "sundry creditors"
GST_TYPES = {
    "regular": "REGISTERED",
    "composition": "COMPOSITION",
    "consumer": "CONSUMER",
    "unregistered": "UNREGISTERED",
    "unregistered/consumer": "UNREGISTERED",
}
_BAD_REFS = re.compile(r"&#(x[0-9a-fA-F]+|[0-9]+);")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")


@dataclass
class Ledger:
    name: str
    kind: str  # CLIENT or VENDOR
    gstin: str = ""
    gst_type: str = ""  # Tally's words, e.g. "Regular"
    state: str = ""
    country: str = ""
    pan: str = ""
    email: str = ""
    phone: str = ""
    mailing_name: str = ""
    address: list[str] = field(default_factory=list)
    pincode: str = ""
    credit_days: str = ""


@dataclass
class StockItem:
    name: str
    unit: str = ""
    description: str = ""
    hsn: str = ""
    gst_rate: str = ""
    rate: str = ""


@dataclass
class Masters:
    ledgers: list[Ledger]
    items: list[StockItem]
    other_ledgers: int


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    elif len(data) > 1 and data[1:2] == b"\x00":
        text = data.decode("utf-16-le")
    elif len(data) > 1 and data[0:1] == b"\x00":
        text = data.decode("utf-16-be")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    return text.lstrip("﻿")


def _keep_ref(m: re.Match[str]) -> str:
    ref = m.group(1)
    n = int(ref[1:], 16) if ref[0] in "xX" else int(ref)
    return m.group(0) if n in (9, 10, 13) or n >= 32 else ""


def _text(el: Element | None) -> str:
    return " ".join((el.text or "").split()) if el is not None else ""


def _first(el: Element, *paths: str) -> str:
    """The first non-empty text among the paths (ElementTree paths)."""
    for path in paths:
        for found in el.iterfind(path):
            if value := _text(found):
                return value
    return ""


def _name(el: Element) -> str:
    return " ".join((el.get("NAME") or "").split()) or _first(
        el, "NAME.LIST/NAME", "LANGUAGENAME.LIST/NAME.LIST/NAME", "NAME"
    )


def _latest(el: Element, path: str) -> list[Element]:
    """Entries by APPLICABLEFROM or DATE (YYYYMMDD), newest first; undated last."""
    found = list(el.iterfind(path))
    return sorted(found, key=lambda e: _first(e, "APPLICABLEFROM", "DATE") or "0", reverse=True)


def _group_of(parent: str, groups: dict[str, str]) -> str:
    """Follow the group up until Sundry Debtors / Creditors (or the top)."""
    seen: set[str] = set()
    key = parent.lower()
    while key and key not in (DEBTORS, CREDITORS) and key not in seen:
        seen.add(key)
        key = groups.get(key, "").lower()
    return key


def _ledger(el: Element, kind: str) -> Ledger:
    registration = _latest(el, "LEDGSTREGDETAILS.LIST")
    mailing = _latest(el, "LEDMAILINGDETAILS.LIST")
    address = [_text(a) for a in el.iterfind("ADDRESS.LIST/ADDRESS")]
    if not any(address) and mailing:
        address = [_text(a) for a in mailing[0].iterfind("ADDRESS.LIST/ADDRESS")]
    days = re.match(r"\s*(\d+)", _first(el, "BILLCREDITPERIOD"))

    def reg(tag: str) -> str:
        return next((v for r in registration if (v := _first(r, tag))), "")

    def mail(tag: str) -> str:
        return next((v for m in mailing if (v := _first(m, tag))), "")

    return Ledger(
        name=_name(el),
        kind=kind,
        gstin=(_first(el, "PARTYGSTIN") or reg("GSTIN")).replace(" ", "").upper(),
        gst_type=_first(el, "GSTREGISTRATIONTYPE") or reg("GSTREGISTRATIONTYPE"),
        state=_first(el, "LEDSTATENAME", "STATENAME") or mail("STATE") or reg("STATE"),
        country=_first(el, "COUNTRYNAME", "COUNTRYOFRESIDENCE") or mail("COUNTRY"),
        pan=_first(el, "INCOMETAXNUMBER").replace(" ", "").upper(),
        email=_first(el, "EMAIL"),
        phone=_first(el, "LEDGERMOBILE", "LEDGERPHONE"),
        mailing_name=_first(el, "MAILINGNAME.LIST/MAILINGNAME") or mail("MAILINGNAME"),
        address=[a for a in address if a],
        pincode=(_first(el, "PINCODE") or mail("PINCODE")).replace(" ", ""),
        credit_days=days.group(1) if days else "",
    )


def _number(text: str) -> str:
    """'380.00/Bag' -> '380.00'; '18 %' -> '18'; nothing usable -> ''."""
    m = re.match(r"\s*(-?[\d,]*\.?\d+)", text)
    if not m:
        return ""
    try:
        value = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return ""
    return str(abs(value))


def _item(el: Element) -> StockItem:
    hsn, rate = "", ""
    for details in _latest(el, "GSTDETAILS.LIST"):
        hsn = hsn or _first(details, "HSNCODE")
        for head in details.iterfind(".//RATEDETAILS.LIST"):
            duty = _first(head, "GSTRATEDUTYHEAD").lower()
            if not rate and duty in ("igst", "integrated tax"):
                rate = _number(_first(head, "GSTRATE"))
        if hsn and rate:
            break
    for details in _latest(el, "HSNDETAILS.LIST"):
        hsn = hsn or _first(details, "HSNCODE")
    price = next((p for e in _latest(el, "STANDARDPRICELIST.LIST") if (p := _first(e, "RATE"))), "")
    return StockItem(
        name=_name(el),
        unit=_first(el, "BASEUNITS"),
        description=_first(el, "DESCRIPTION.LIST/DESCRIPTION", "DESCRIPTION"),
        hsn=hsn.replace(" ", ""),
        gst_rate=rate,
        rate=_number(price),
    )


def read(data: bytes) -> Masters:
    text = _DECLARATION.sub("", _CONTROL.sub("", _BAD_REFS.sub(_keep_ref, _decode(data))))
    try:
        root: Any = ElementTree.fromstring(text)
    except (ElementTree.ParseError, DefusedXmlException) as e:
        raise Invalid(
            "file", "This is not an XML file exported from Tally.", code="not_tally_xml"
        ) from e
    groups = {_name(g).lower(): _first(g, "PARENT") for g in root.iter("GROUP")}
    ledgers, other = [], 0
    for el in root.iter("LEDGER"):
        group = _group_of(_first(el, "PARENT"), groups)
        if group == DEBTORS:
            ledgers.append(_ledger(el, "CLIENT"))
        elif group == CREDITORS:
            ledgers.append(_ledger(el, "VENDOR"))
        else:
            other += 1
    items = [_item(el) for el in root.iter("STOCKITEM")]
    if not ledgers and not items and not other:
        raise Invalid(
            "file",
            "No ledgers or stock items found. In Tally, export the masters as XML.",
            code="no_masters",
        )
    return Masters([x for x in ledgers if x.name], [x for x in items if x.name], other)
