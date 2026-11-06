"""Reading a bank statement file (CSV or Excel) into lines (Part B).

Banks name their columns differently ("Withdrawal Amt.", "Debit", "Dr"...), put
title rows above the header and totals below the lines, and write dates day
first. Columns are found by name; when they cannot be, the person chooses them
once (`mapping`: field -> the header as written) and the web app remembers that
choice for this bank's layout. Rows without a date are not transactions
(opening balance, totals, footers): they are skipped and reported.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.core.errors import Invalid
from apps.core.sheets import normalise, raw_rows

HEADER_SEARCH_ROWS = 30
FIELDS = ("date", "narration", "reference", "money_in", "money_out", "amount", "dr_cr", "balance")

# field -> header names (normalised), best first: a transaction date before a value date
ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "txn_date",
        "transaction_date",
        "tran_date",
        "trans_date",
        "date",
        "posting_date",
        "post_date",
        "value_date",
        "value_dt",
        "txn_dt",
    ),
    "narration": (
        "narration",
        "description",
        "particulars",
        "transaction_remarks",
        "remarks",
        "transaction_details",
        "details",
        "transaction_particulars",
        "transaction_description",
    ),
    "reference": (
        "chq_ref_no",
        "chq_ref_number",
        "ref_no_cheque_no",
        "ref_no_chq_no",
        "chq_no_ref_no",
        "cheque_no",
        "cheque_number",
        "chq_no",
        "ref_no",
        "reference",
        "reference_no",
        "utr",
        "utr_no",
        "transaction_id",
        "instrument_id",
    ),
    "money_out": (
        "withdrawal_amt",
        "withdrawal_amount",
        "withdrawal_amount_inr",
        "withdrawal_amt_inr",
        "withdrawals",
        "withdrawal",
        "debit",
        "debit_amount",
        "debit_amt",
        "debits",
        "dr",
    ),
    "money_in": (
        "deposit_amt",
        "deposit_amount",
        "deposit_amount_inr",
        "deposit_amt_inr",
        "deposits",
        "deposit",
        "credit",
        "credit_amount",
        "credit_amt",
        "credits",
        "cr",
    ),
    "amount": ("amount", "transaction_amount", "amount_inr", "txn_amount"),
    "dr_cr": ("dr_cr", "cr_dr", "debit_credit", "credit_debit", "type", "transaction_type"),
    "balance": (
        "closing_balance",
        "balance",
        "balance_inr",
        "running_balance",
        "available_balance",
    ),
}
OUT_WORDS = {"dr", "d", "debit", "withdrawal", "w"}
IN_WORDS = {"cr", "c", "credit", "deposit"}
MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}


@dataclass(frozen=True)
class Line:
    row: int
    line_date: date
    narration: str
    reference: str | None
    money_in: Decimal
    money_out: Decimal
    balance: Decimal | None


@dataclass
class Statement:
    headers: list[str]  # the header row, as written
    columns: dict[str, str]  # field -> header used
    ready: bool  # date, narration and an amount were found
    lines: list[Line] = field(default_factory=list)
    skipped_rows: list[int] = field(default_factory=list)


def parse_date(value: str) -> date | None:
    """Day first, as Indian banks write it: 05/10/2026, 05-10-26, 05-Oct-2026,
    5 Oct 2026, 05.10.2026; or an Excel date (2026-10-05T00:00:00)."""
    v = value.strip()
    if not v:
        return None
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", v):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", v):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[\s\-/]([A-Za-z]{3})[A-Za-z]*[\s\-/,]*(\d{2}|\d{4})", v):
        d, y = int(m[1]), int(m[3])
        mo = MONTHS.get(m[2].lower(), 0)
    else:
        return None
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_money(value: str) -> Decimal | None:
    """'1,23,456.50', '₹ 500', '1,000.00 Cr', '(250.00)': the amount, unsigned
    except for a leading minus or brackets; None when empty."""
    v = re.sub(r"(?i)\b(cr|dr|inr|rs)\b\.?|[₹,\s]", "", value.strip())
    negative = v.startswith("-") or (v.startswith("(") and v.endswith(")"))
    v = v.strip("()-+")
    if not v:
        return None
    try:
        amount = Decimal(v)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def _find(headers: list[str], mapping: dict[str, str] | None) -> dict[str, str]:
    norm = {normalise(h): h for h in headers if h.strip()}
    columns: dict[str, str] = {}
    for f in FIELDS:
        if mapping and mapping.get(f):
            if mapping[f] not in headers:
                raise Invalid(f"mapping.{f}", f"No column called “{mapping[f]}”.", code="not_found")
            columns[f] = mapping[f]
            continue
        hit = next((norm[a] for a in ALIASES[f] if a in norm), None)
        if hit is not None and hit not in columns.values():
            columns[f] = hit
    return columns


def _ready(columns: dict[str, str]) -> bool:
    has_amount = ("money_in" in columns and "money_out" in columns) or "amount" in columns
    return "date" in columns and "narration" in columns and has_amount


def read(data: bytes, mapping: dict[str, str] | None = None) -> Statement:
    raw = raw_rows(data)
    header_at, best = 0, None
    for i, row in enumerate(raw[:HEADER_SEARCH_ROWS]):
        cols = _find(row, None) if not mapping else {}
        if mapping and all(v in row for v in mapping.values() if v):
            best = (i, row)
            break
        if cols and _ready(cols):
            best = (i, row)
            break
    if best is None:
        # no header found: offer the first non-empty row's cells to choose from
        first = next((r for r in raw[:HEADER_SEARCH_ROWS] if any(c.strip() for c in r)), [])
        return Statement(headers=[c for c in first if c.strip()], columns={}, ready=False)
    header_at, headers = best
    columns = _find(headers, mapping)
    statement = Statement(
        headers=[h for h in headers if h.strip()], columns=columns, ready=_ready(columns)
    )
    if not statement.ready:
        return statement
    at = {f: headers.index(h) for f, h in columns.items()}

    def cell(row: list[str], f: str) -> str:
        i = at.get(f)
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(raw[header_at + 1 :], start=header_at + 2):
        if not any(c.strip() for c in row):
            continue
        day = parse_date(cell(row, "date"))
        if day is None:
            statement.skipped_rows.append(n)
            continue
        money_in = money_out = Decimal("0.00")
        if "money_in" in at:
            money_in = abs(parse_money(cell(row, "money_in")) or Decimal("0"))
            money_out = abs(parse_money(cell(row, "money_out")) or Decimal("0"))
        else:
            amount = parse_money(cell(row, "amount")) or Decimal("0")
            kind = normalise(cell(row, "dr_cr"))
            raw_amount = cell(row, "amount").lower()
            if kind in OUT_WORDS or raw_amount.endswith("dr") or (not kind and amount < 0):
                money_out = abs(amount)
            elif kind in IN_WORDS or raw_amount.endswith("cr") or amount > 0:
                money_in = abs(amount)
        if (money_in > 0) == (money_out > 0):  # nothing (or both): not a transaction we can use
            statement.skipped_rows.append(n)
            continue
        balance = parse_money(cell(row, "balance")) if "balance" in at else None
        statement.lines.append(
            Line(
                row=n,
                line_date=day,
                narration=cell(row, "narration")[:500],
                reference=(cell(row, "reference") or None) and cell(row, "reference")[:100],
                money_in=money_in.quantize(Decimal("0.01")),
                money_out=money_out.quantize(Decimal("0.01")),
                balance=balance.quantize(Decimal("0.01")) if balance is not None else None,
            )
        )
    return statement


def fingerprints(account: str, lines: list[Line]) -> list[str]:
    """One per line: the same line imported again gets the same fingerprint (and
    is skipped); two identical lines in one file are told apart by their order."""
    seen: Counter[tuple[object, ...]] = Counter()
    out = []
    for line in lines:
        key = (
            account.strip().lower(),
            line.line_date,
            line.narration,
            line.reference,
            line.money_in,
            line.money_out,
        )
        seen[key] += 1
        text = "|".join(str(k) for k in key) + f"|{seen[key]}"
        out.append(hashlib.sha256(text.encode()).hexdigest())
    return out
