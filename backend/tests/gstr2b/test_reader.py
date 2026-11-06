"""Reading GSTR-2B JSON as the GST portal gives it (Part B)."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from apps.core.errors import Invalid
from apps.gstr2b import reader

OURS = "32AABCD1234E1Z5"
STEEL = "32AAACK1234M1Z8"
CEMENT = "33AAACC5678P1Z2"


def portal(docdata: dict[str, Any], wrapped: bool = True, **extra: Any) -> bytes:
    body = {
        "gstin": OURS,
        "rtnprd": "102026",
        "version": "1.0",
        "gendt": "14-11-2026",
        "docdata": docdata,
        **extra,
    }
    return json.dumps({"chksum": "x", "data": body} if wrapped else body).encode()


B2B = [
    {
        "ctin": STEEL,
        "trdnm": "Kerala Steel Traders",
        "supfildt": "11-11-2026",
        "supprd": "102026",
        "inv": [
            {
                "inum": "KST/101",
                "typ": "R",
                "dt": "10-10-2026",
                "val": 59000,
                "pos": "32",
                "rev": "N",
                "itcavl": "Y",
                "rsn": "",
                "diffprcnt": 1,
                "srctyp": "e-Invoice",
                "txval": 50000,
                "igst": 0,
                "cgst": 4500,
                "sgst": 4500,
                "cess": 0,
            },
            {
                "inum": "KST/102",
                "typ": "R",
                "dt": "28-10-2026",
                "val": 11800,
                "pos": "32",
                "rev": "Y",
                "itcavl": "N",
                "rsn": "P",
                "txval": 10000,
                "cgst": 900,
                "sgst": 900,
            },
        ],
    }
]


def test_reads_invoices_with_their_tax_and_itc() -> None:
    r = reader.read(portal({"b2b": B2B}))
    assert (r.gstin, r.period, r.generated_on) == (OURS, date(2026, 10, 1), date(2026, 11, 14))
    first, second = r.docs
    assert (first.section, first.doc_type, first.supplier_gstin, first.number) == (
        "B2B",
        "INVOICE",
        STEEL,
        "KST/101",
    )
    assert first.doc_date == date(2026, 10, 10)
    assert (first.taxable_value, first.cgst, first.sgst, first.tax) == (
        Decimal("50000.00"),
        Decimal("4500.00"),
        Decimal("4500.00"),
        Decimal("9000.00"),
    )
    assert (first.reverse_charge, first.itc_available) == (False, True)
    assert (second.reverse_charge, second.itc_available, second.itc_reason) == (True, False, "P")


def test_reads_notes_amendments_and_item_wise_amounts() -> None:
    r = reader.read(
        portal(
            {
                "cdnr": [
                    {
                        "ctin": CEMENT,
                        "trdnm": "Coastal Cement",
                        "nt": [
                            {
                                "ntnum": "CN-7",
                                "typ": "C",
                                "dt": "15-10-2026",
                                "val": 1180,
                                "itms": [{"num": 1, "itm_det": {"txval": 1000, "iamt": 180}}],
                            }
                        ],
                    }
                ],
                "b2ba": [
                    {
                        "ctin": STEEL,
                        "inv": [
                            {
                                "inum": "KST/099A",
                                "oinum": "KST/099",
                                "dt": "30-09-2026",
                                "txval": 2000,
                                "igst": 360,
                            }
                        ],
                    }
                ],
                "isd": [{"ctin": "32AAAAA0000A1Z0", "doclist": []}],
            },
            wrapped=False,  # some downloads have no "data" wrapper
        )
    )
    note = next(d for d in r.docs if d.section == "CDNR")
    assert (note.doc_type, note.taxable_value, note.igst) == (
        "CREDIT_NOTE",
        Decimal("1000.00"),
        Decimal("180.00"),
    )
    amended = next(d for d in r.docs if d.section == "B2BA")
    assert (amended.number, amended.original_number) == ("KST/099A", "KST/099")
    assert r.skipped == {"ISD": 1}


def test_refuses_what_is_not_a_gstr2b() -> None:
    for data in (b"not json", b'{"data": {"gstin": "x"}}', b"[1, 2]"):
        with pytest.raises(Invalid) as e:
            reader.read(data)
        assert e.value.code == "not_gstr2b"
    with pytest.raises(Invalid):
        reader.read(portal({}, rtnprd="13-2026"))
