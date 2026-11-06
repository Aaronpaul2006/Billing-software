"""Reading bank statement files (Part B): the columns of the common Indian banks,
day-first dates, Indian amounts, title and total rows, a chosen mapping."""

from datetime import date
from decimal import Decimal

import pytest

from apps.banking.statement import fingerprints, parse_date, parse_money, read

HDFC = b"""HDFC BANK Ltd.,,,,,,
Statement of account,,,,,,
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
05/10/26,NEFT CR-SBIN0001234-SKYLINE DEVELOPERS,SBIN26278123456,05/10/26,,"5,41,014.00","6,41,014.00"
06/10/26,CHQ PAID-RAVI KUMAR,000123,06/10/26,"58,500.00",,"5,82,514.00"
07/10/26,SMS CHARGES,,07/10/26,17.70,,"5,82,496.30"
,,,,,,
Statement Summary :-,Opening Balance,Dr Count,Cr Count,Debits,Credits,Closing Bal
"""

SBI = b"""Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
5 Oct 2026,5 Oct 2026,BY TRANSFER-UPI/CR/628212345/ANIL KUMAR,UPI628212345,,"2,35,233.00","8,76,247.30"
12-Oct-2026,12-Oct-2026,TO TRANSFER-NEFT KERALA STEEL TRADERS,N2826100045,"1,18,000.00",,"7,58,247.30"
"""

ONE_AMOUNT = b"""Transaction Date,Transaction Remarks,Amount (INR),Dr/Cr,Balance (INR)
2026-10-05,IMPS IN ANIL KUMAR,"25,000.00",CR,"25,000.00"
2026-10-06,ATM WDL,"5,000.00",DR,"20,000.00"
"""


def test_hdfc_layout_with_titles_and_a_summary() -> None:
    s = read(HDFC)
    assert s.ready
    assert s.columns["date"] == "Date"
    assert s.columns["reference"] == "Chq./Ref.No."
    assert (s.columns["money_out"], s.columns["money_in"]) == ("Withdrawal Amt.", "Deposit Amt.")
    assert [(x.line_date, x.money_in, x.money_out) for x in s.lines] == [
        (date(2026, 10, 5), Decimal("541014.00"), Decimal("0.00")),
        (date(2026, 10, 6), Decimal("0.00"), Decimal("58500.00")),
        (date(2026, 10, 7), Decimal("0.00"), Decimal("17.70")),
    ]
    assert s.lines[0].reference == "SBIN26278123456"
    assert s.lines[0].balance == Decimal("641014.00")
    assert s.skipped_rows == [8]  # the summary row; the empty row is not counted


def test_sbi_layout_and_month_names() -> None:
    s = read(SBI)
    assert s.ready
    assert s.columns["date"] == "Txn Date"  # the transaction date, not the value date
    assert [(x.line_date, x.money_in, x.money_out, x.reference) for x in s.lines] == [
        (date(2026, 10, 5), Decimal("235233.00"), Decimal("0.00"), "UPI628212345"),
        (date(2026, 10, 12), Decimal("0.00"), Decimal("118000.00"), "N2826100045"),
    ]


def test_one_amount_column_with_dr_cr() -> None:
    s = read(ONE_AMOUNT)
    assert s.ready
    assert [(x.money_in, x.money_out) for x in s.lines] == [
        (Decimal("25000.00"), Decimal("0.00")),
        (Decimal("0.00"), Decimal("5000.00")),
    ]


def test_unknown_columns_are_chosen_once() -> None:
    odd = b"""When,What happened,Paid out,Paid in
05/10/2026,Cement,"1,000.00",
06/10/2026,Client,,"2,000.00"
"""
    s = read(odd)
    assert not s.ready
    assert s.headers == ["When", "What happened", "Paid out", "Paid in"]
    mapped = read(
        odd,
        {
            "date": "When",
            "narration": "What happened",
            "money_out": "Paid out",
            "money_in": "Paid in",
        },
    )
    assert mapped.ready
    assert [(x.narration, x.money_in, x.money_out) for x in mapped.lines] == [
        ("Cement", Decimal("0.00"), Decimal("1000.00")),
        ("Client", Decimal("2000.00"), Decimal("0.00")),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("05/10/2026", date(2026, 10, 5)),
        ("5/10/26", date(2026, 10, 5)),
        ("05-10-2026", date(2026, 10, 5)),
        ("05.10.2026", date(2026, 10, 5)),
        ("05-Oct-2026", date(2026, 10, 5)),
        ("5 Oct 26", date(2026, 10, 5)),
        ("2026-10-05T00:00:00", date(2026, 10, 5)),
        ("31/02/2026", None),
        ("Opening balance", None),
        ("", None),
    ],
)
def test_dates_are_day_first(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,23,456.50", Decimal("123456.50")),
        ("₹ 500", Decimal("500")),
        ("1,000.00 Cr", Decimal("1000.00")),
        ("-250.00", Decimal("-250.00")),
        ("(250.00)", Decimal("-250.00")),
        ("", None),
        ("n/a", None),
    ],
)
def test_amounts_as_indian_banks_write_them(text: str, expected: Decimal | None) -> None:
    assert parse_money(text) == expected


def test_the_same_line_twice_in_one_file_is_kept_apart_but_a_reimport_is_not() -> None:
    twice = b"""Date,Narration,Withdrawal Amt.,Deposit Amt.
07/10/26,SMS CHARGES,17.70,
07/10/26,SMS CHARGES,17.70,
"""
    lines = read(twice).lines
    first = fingerprints("HDFC 1234", lines)
    assert len(set(first)) == 2
    assert fingerprints("hdfc 1234 ", read(twice).lines) == first  # same file again: same prints
    assert fingerprints("SBI 9999", lines) != first  # another account
