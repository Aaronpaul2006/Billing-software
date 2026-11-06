"""GSTR-2B from the portal's Excel download (Part B): the same documents as
the JSON, so the same reconciliation (see test_api.py)."""

import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.errors import Invalid
from apps.gstr2b import reader_xlsx
from tests.gstr2b.test_api import CEMENT, STEEL, Books

TITLE = ["Goods and Services Tax - GSTR-2B"]


def workbook(
    gstin: str, b2b: list[list[Any]], cdnr: list[list[Any]], b2ba: list[list[Any]]
) -> bytes:
    import openpyxl

    book = openpyxl.Workbook()
    readme = book.create_sheet("Read me", 0)
    del book["Sheet"]  # the empty sheet a new workbook starts with
    for row in (
        TITLE,
        [],
        ["Financial Year", "2026-27"],
        ["Tax Period", "October"],
        ["GSTIN", gstin],
        ["Legal Name", "Nair Constructions"],
        ["Date of generation", "14-11-2026"],
    ):
        readme.append(row)
    sheet = book.create_sheet("B2B")
    sheet.append(["Taxable inbound supplies received from registered persons"])
    sheet.append([])
    sheet.append(
        [
            "GSTIN of supplier",
            "Trade/Legal name",
            "Invoice details",
            "",
            "",
            "",
            "Place of supply",
            "Supply Attract Reverse Charge",
            "Taxable Value (₹)",
            "Tax Amount",
            "",
            "",
            "",
            "GSTR-1/IFF/GSTR-5 Period",
            "GSTR-1/IFF/GSTR-5 Filing Date",
            "ITC Availability",
            "Reason",
            "Applicable % of Tax Rate",
            "Source",
            "IRN",
            "IRN Date",
        ]
    )
    sheet.append(
        [
            "",
            "",
            "Invoice number",
            "Invoice type",
            "Invoice Date",
            "Invoice Value(₹)",
            "",
            "",
            "",
            "Integrated Tax(₹)",
            "Central Tax(₹)",
            "State/UT Tax(₹)",
            "Cess(₹)",
        ]
    )
    for r in b2b:
        sheet.append(r)
    sheet.append(["Total", "", "", "", "", 999999])  # the portal's totals row
    notes = book.create_sheet("B2B-CDNR")
    notes.append(["Debit/Credit notes (Original)"])
    notes.append(
        [
            "GSTIN of supplier",
            "Trade/Legal name",
            "Credit note/Debit note details",
            "",
            "",
            "",
            "",
            "Place of supply",
            "Supply Attract Reverse Charge",
            "Taxable Value (₹)",
            "Tax Amount",
            "",
            "",
            "",
            "Period",
            "Filing Date",
            "ITC Availability",
            "Reason",
        ]
    )
    notes.append(
        [
            "",
            "",
            "Note number",
            "Note type",
            "Note Supply type",
            "Note date",
            "Note Value (₹)",
            "",
            "",
            "",
            "Integrated Tax(₹)",
            "Central Tax(₹)",
            "State/UT Tax(₹)",
            "Cess(₹)",
        ]
    )
    for r in cdnr:
        notes.append(r)
    amended = book.create_sheet("B2BA")
    amended.append(["Amendments to previously filed invoices"])
    amended.append(
        [
            "Original details",
            "",
            "",
            "Revised details",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "ITC Availability",
        ]
    )
    amended.append(
        [
            "Invoice number",
            "Invoice Date",
            "GSTIN of supplier",
            "Trade/Legal name",
            "Invoice number",
            "Invoice type",
            "Invoice Date",
            "Invoice Value(₹)",
            "Place of supply",
            "Supply Attract Reverse Charge",
            "Taxable Value (₹)",
            "Integrated Tax(₹)",
            "Central Tax(₹)",
            "State/UT Tax(₹)",
            "Cess(₹)",
            "Period",
            "ITC Availability",
        ]
    )
    amended.append(["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    for r in b2ba:
        amended.append(r)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def inv(
    gstin: str,
    name: str,
    number: str,
    day: str,
    value: float,
    igst: float,
    cgst: float,
    sgst: float,
    itc: str = "Yes",
) -> list[Any]:
    return [
        gstin,
        name,
        number,
        "Regular",
        day,
        value + igst + cgst + sgst,
        "32-Kerala",
        "No",
        value,
        igst,
        cgst,
        sgst,
        0,
        "Oct-2026",
        "11-11-2026",
        itc,
        "",
        "",
        "e-Invoice",
    ]


def october(gstin: str) -> bytes:
    return workbook(
        gstin,
        [
            inv(STEEL, "Kerala Steel Traders", "KST/101", "10-10-2026", 50000, 0, 4500, 4500),
            inv(STEEL, "Kerala Steel Traders", "KST/102", "28-10-2026", 10000, 0, 900, 900),
            inv(CEMENT, "Coastal Cement", "CC/77", "15-10-2026", 20000, 3600, 0, 0),
            inv(CEMENT, "Coastal Cement", "CC/80", "20-10-2026", 5000, 900, 0, 0),
        ],
        [
            [
                CEMENT,
                "Coastal Cement",
                "CN-7",
                "Credit Note",
                "Regular",
                "25-10-2026",
                1180,
                "32-Kerala",
                "No",
                1000,
                180,
                0,
                0,
                0,
                "Oct-2026",
                "11-11-2026",
                "Yes",
                "",
            ]
        ],
        [],
    )


def test_reads_the_excel_download() -> None:
    r = reader_xlsx.read(
        workbook(
            "32AABCD1234E1Z5",
            [
                inv(
                    STEEL,
                    "Kerala Steel Traders",
                    "KST/101",
                    "10-10-2026",
                    50000,
                    0,
                    4500,
                    4500,
                    itc="No",
                )
            ],
            [
                [
                    CEMENT,
                    "Coastal Cement",
                    "DN-2",
                    "Debit Note",
                    "Regular",
                    "25-10-2026",
                    590,
                    "33-Tamil Nadu",
                    "Yes",
                    500,
                    90,
                    0,
                    0,
                    0,
                    "Oct-2026",
                    "11-11-2026",
                    "Yes",
                    "",
                ]
            ],
            [
                [
                    "KST/099",
                    "30-09-2026",
                    STEEL,
                    "Kerala Steel Traders",
                    "KST/099A",
                    "Regular",
                    "30-09-2026",
                    2360,
                    "Kerala",
                    "No",
                    2000,
                    360,
                    0,
                    0,
                    0,
                    "Oct-2026",
                    "Yes",
                ]
            ],
        )
    )
    assert (r.gstin, r.period, r.generated_on) == (
        "32AABCD1234E1Z5",
        date(2026, 10, 1),
        date(2026, 11, 14),
    )
    by = {d.number: d for d in r.docs}
    assert set(by) == {"KST/101", "DN-2", "KST/099A"}  # the totals row is not a document
    first = by["KST/101"]
    assert (first.section, first.doc_type, first.supplier_gstin) == ("B2B", "INVOICE", STEEL)
    assert (first.taxable_value, first.cgst, first.sgst, first.tax) == (
        Decimal("50000.00"),
        Decimal("4500.00"),
        Decimal("4500.00"),
        Decimal("9000.00"),
    )
    assert (first.itc_available, first.place_of_supply) == (False, "32")
    note = by["DN-2"]
    assert (note.section, note.doc_type, note.reverse_charge, note.place_of_supply) == (
        "CDNR",
        "DEBIT_NOTE",
        True,
        "33",
    )
    amended = by["KST/099A"]
    assert (amended.section, amended.original_number, amended.place_of_supply) == (
        "B2BA",
        "KST/099",
        "32",
    )


def test_refuses_what_is_not_the_download() -> None:
    for data in (b"PK not really a zip", workbook("", [], [], [])):
        with pytest.raises(Invalid) as e:
            reader_xlsx.read(data)
        assert e.value.code == "not_gstr2b"


pytestmark = pytest.mark.django_db


def test_the_excel_reconciles_like_the_json() -> None:
    b = Books()
    r = APIClient().post(
        "/api/v1/gstr2b-returns",
        {"file": SimpleUploadedFile("GSTR2B_102026.xlsx", october(b.gstin))},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        **b.h(),
    )
    assert r.status_code == 201, r.content
    assert (r.json()["period"], r.json()["doc_count"]) == ("2026-10-01", 5)
    s = b.recon(r.json()["id"]).json()["summary"]
    assert (s["matched"], s["amounts_differ"], s["not_in_books"], s["not_in_2b"]) == (2, 1, 2, 1)
    assert (s["itc_in_2b"], s["itc_at_risk"]) == ("15120.00", "1440.00")
