"""GSTR-1 JSON (offline tool shape GST3.2.4) from a month of real documents.

The expected numbers are worked out by hand below; amounts must appear in the
JSON exactly as written (2 decimals, never through float).
"""

import json
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.exports.models import Export
from apps.parties.models import Party
from apps.projects.models import Project
from apps.tenants.models import GstRegistration
from tests.documents.test_drafts import RCC, World
from tests.documents.test_lifecycle import act, series
from tests.factories import gstin

pytestmark = pytest.mark.django_db

CEMENT = {
    "description": "OPC 53 cement",
    "sac_hsn": "2523",
    "unit": "Bags",
    "quantity": "100",
    "rate": "380.00",
    "gst_rate": "28.00",
}
SAND = {  # at 0 %: reported in Table 8 as nil-rated
    "description": "River sand",
    "sac_hsn": "2505",
    "unit": "cum",
    "quantity": "1",
    "rate": "1000.00",
    "gst_rate": "0.00",
}


class Month:
    """October 2026 for a Kerala contractor (registration in state 32)."""

    inv_local: dict[str, Any]

    def __init__(self) -> None:
        self.w = w = World()
        series(w)
        series(w, "CREDIT_NOTE", "CN/")
        with tenant_context(w.t.tenant_id, w.t.user_id):
            self.gstin = str(GstRegistration.objects.get(pk=w.t.registration_id).gstin)
            self.karnataka = Party.objects.create(
                display_name="Bengaluru Builders",
                gst_treatment="REGISTERED",
                gstin=gstin("29", pan="AAACK1234K"),
                pan="AAACK1234K",
                state_code="29",
                created_by_id=w.t.user_id,
            )
            self.site_29 = Project.objects.create(
                code="BLR-1",
                name="BLR-1",
                client_party=self.karnataka,
                gst_registration_id=w.t.registration_id,
                site_state_code="29",
                created_by_id=w.t.user_id,
            )
            self.consumer_29 = Party.objects.create(
                display_name="Anil Kumar",
                gst_treatment="CONSUMER",
                state_code="29",
                created_by_id=w.t.user_id,
            )
            self.consumer_32 = Party.objects.create(
                display_name="Mary Joseph",
                gst_treatment="CONSUMER",
                state_code="32",
                created_by_id=w.t.user_id,
            )

    def issue(self, **body: Any) -> dict[str, Any]:
        draft = self.w.create(**body)
        assert draft.status_code == 201, draft.content
        issued = act(self.w, draft.json(), "issue")
        assert issued.status_code == 200, issued.content
        result: dict[str, Any] = issued.json()
        return result

    def credit(self, invoice: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
        draft = act(
            self.w, invoice, "credit-notes", body={"doc_date": "2026-10-28", "lines": lines}
        )
        assert draft.status_code == 201, draft.content
        issued: dict[str, Any] = act(self.w, draft.json(), "issue").json()
        return issued


@pytest.fixture
def month() -> Month:
    m = Month()
    m.issue(doc_date="2026-09-30")  # INV/0001, September: not in October's return
    m.inv_local = m.issue(lines=[RCC, SAND])  # INV/0002 registered, intra-State
    m.issue(  # INV/0003 registered, inter-State
        party_id=str(m.karnataka.pk), project_id=str(m.site_29.pk), lines=[RCC, CEMENT]
    )
    m.issue(party_id=str(m.consumer_29.pk), project_id=None)  # INV/0004 B2C large
    small = m.issue(  # INV/0005 B2C small, intra-State
        party_id=str(m.consumer_32.pk), project_id=None, lines=[{**RCC, "quantity": "1"}]
    )
    cancelled = m.issue(lines=[{**RCC, "quantity": "1"}])  # INV/0006, then cancelled
    act(m.w, cancelled, "cancel", body={"reason": "Wrong client"})
    m.credit(m.inv_local, [{**RCC, "quantity": "1"}])  # CN/0001 to a registered client
    m.credit(small, [{**RCC, "quantity": "0.5"}])  # CN/0002 netted into B2C small
    return m


def gstr1(
    month: Month, s3: Any, run: Any, period: str = "2026-10"
) -> tuple[dict[str, Any], str, Any]:
    w = month.w
    with run():
        response = APIClient().post(
            "/api/v1/exports",
            {
                "kind": "GSTR1",
                "format": "JSON",
                "params": {"gst_registration_id": str(w.t.registration_id), "period": period},
            },
            format="json",
            **w.h(),
        )
    assert response.status_code == 202, response.content
    body = APIClient().get(f"/api/v1/exports/{response.json()['id']}", **w.h()).json()
    with tenant_context(w.t.tenant_id, w.t.user_id):
        key = Export.objects.get(pk=body["id"]).storage_key
    raw = s3.get_object(Bucket="test-bucket", Key=key)["Body"].read().decode("utf-8")
    return json.loads(raw), raw, body


def test_a_month_of_documents_as_gstr1(month: Month, s3: Any, run: Any) -> None:
    data, raw, export = gstr1(month, s3, run)
    assert export["status"] == "READY"
    assert export["file_name"] == f"gstr1_{month.gstin}_102026.json"
    assert export["row_count"] == 6  # INV/0002-0005, CN/0001-0002 (cancelled: Table 13 only)
    assert export["warnings"][0].startswith("Import this file into the GST offline tool")
    assert list(data)[:4] == ["gstin", "fp", "version", "hash"]
    assert (data["gstin"], data["fp"], data["version"], data["hash"]) == (
        month.gstin,
        "102026",
        "GST3.2.4",
        "hash",
    )

    # B2B: RCC 42.5 cum x 6,800 = 2,89,000 at 18 %; sand at 0 % stays out of the items.
    local = next(b for b in data["b2b"] if b["ctin"] == month.w.client.gstin)
    [inv] = local["inv"]
    assert inv == {
        "inum": "INV/0002",
        "idt": "19-10-2026",
        "val": 342020.0,  # 2,89,000 + 26,010 + 26,010 + 1,000 sand
        "pos": "32",
        "rchrg": "N",
        "inv_typ": "R",
        "itms": [
            {
                "num": 1801,
                "itm_det": {
                    "txval": 289000.0,
                    "rt": 18,
                    "camt": 26010.0,
                    "samt": 26010.0,
                    "csamt": 0.0,
                },
            }
        ],
    }
    assert '"txval":289000.00,"rt":18,"camt":26010.00' in raw  # exact decimals
    away = next(b for b in data["b2b"] if b["ctin"] == month.karnataka.gstin)
    assert [i["num"] for i in away["inv"][0]["itms"]] == [1801, 2801]
    assert away["inv"][0]["itms"][1]["itm_det"] == {
        "txval": 38000.0,
        "rt": 28,
        "iamt": 10640.0,
        "csamt": 0.0,
    }

    # B2C large: inter-State to a consumer, over ₹1,00,000.
    assert data["b2cl"] == [
        {
            "pos": "29",
            "inv": [
                {
                    "inum": "INV/0004",
                    "idt": "19-10-2026",
                    "val": 341020.0,
                    "itms": [
                        {
                            "num": 1801,
                            "itm_det": {"txval": 289000.0, "rt": 18, "iamt": 52020.0, "csamt": 0.0},
                        }
                    ],
                }
            ],
        }
    ]
    # B2C small: 6,800 invoiced less 3,400 credited.
    assert data["b2cs"] == [
        {
            "sply_ty": "INTRA",
            "pos": "32",
            "typ": "OE",
            "txval": 3400.0,
            "rt": 18,
            "camt": 306.0,
            "samt": 306.0,
            "csamt": 0.0,
        }
    ]
    [credited] = data["cdnr"]
    assert credited["ctin"] == month.w.client.gstin
    assert credited["nt"][0] | {"itms": None} == {
        "ntty": "C",
        "nt_num": "CN/0001",
        "nt_dt": "28-10-2026",
        "val": 8024.0,
        "pos": "32",
        "rchrg": "N",
        "inv_typ": "R",
        "itms": None,
    }
    assert data["nil"] == {
        "inv": [{"sply_ty": "INTRAB2B", "expt_amt": 0.0, "nil_amt": 1000.0, "ngsup_amt": 0.0}]
    }
    assert data["doc_issue"] == {
        "doc_det": [
            {
                "doc_num": 1,
                "doc_typ": "Invoices for outward supply",
                "docs": [
                    {
                        "num": 1,
                        "from": "INV/0002",
                        "to": "INV/0006",
                        "totnum": 5,
                        "cancel": 1,
                        "net_issue": 4,
                    }
                ],
            },
            {
                "doc_num": 5,
                "doc_typ": "Credit Note",
                "docs": [
                    {
                        "num": 1,
                        "from": "CN/0001",
                        "to": "CN/0002",
                        "totnum": 2,
                        "cancel": 0,
                        "net_issue": 2,
                    }
                ],
            },
        ]
    }
    # HSN: B2B from INV/0002, INV/0003, CN/0001; B2C from INV/0004, INV/0005, CN/0002.
    assert data["hsn"]["hsn_b2b"] == [
        {
            "num": 1,
            "hsn_sc": "2505",
            "uqc": "CBM",
            "qty": 1.0,
            "rt": 0,
            "txval": 1000.0,
            "iamt": 0.0,
            "camt": 0.0,
            "samt": 0.0,
            "csamt": 0.0,
        },
        {
            "num": 2,
            "hsn_sc": "2523",
            "uqc": "BAG",
            "qty": 100.0,
            "rt": 28,
            "txval": 38000.0,
            "iamt": 10640.0,
            "camt": 0.0,
            "samt": 0.0,
            "csamt": 0.0,
        },
        {
            "num": 3,
            "hsn_sc": "9954",
            "uqc": "NA",
            "qty": 0.0,
            "rt": 18,
            "txval": 571200.0,  # 2,89,000 + 2,89,000 - 6,800
            "iamt": 52020.0,
            "camt": 25398.0,  # 26,010 - 612
            "samt": 25398.0,
            "csamt": 0.0,
        },
    ]
    assert data["hsn"]["hsn_b2c"] == [
        {
            "num": 1,
            "hsn_sc": "9954",
            "uqc": "NA",
            "qty": 0.0,
            "rt": 18,
            "txval": 292400.0,  # 2,89,000 + 6,800 - 3,400
            "iamt": 52020.0,
            "camt": 306.0,
            "samt": 306.0,
            "csamt": 0.0,
        }
    ]
    assert any("nil-rated (Table 8)" in w for w in export["warnings"])
    assert any("6-digit HSN" in w for w in export["warnings"])  # 4-digit codes on B2B


def test_a_month_without_documents(month: Month, s3: Any, run: Any) -> None:
    data, _, export = gstr1(month, s3, run, period="2026-08")
    assert data == {"gstin": month.gstin, "fp": "082026", "version": "GST3.2.4", "hash": "hash"}
    assert export["row_count"] == 0


def test_requests_are_checked(month: Month, s3: Any) -> None:
    w = month.w

    def ask(params: dict[str, Any], file_format: str = "JSON") -> Any:
        response = APIClient().post(
            "/api/v1/exports",
            {"kind": "GSTR1", "format": file_format, "params": params},
            format="json",
            **w.h(),
        )
        return response.status_code, {
            e["field"]: e["message"] for e in response.json().get("errors", [])
        }

    reg = str(w.t.registration_id)
    assert ask({"gst_registration_id": reg, "period": "2026-10"}, "CSV")[1] == {
        "format": "GSTR-1 is a JSON file; the registers are CSV or XLSX."
    }
    assert ask({"gst_registration_id": reg, "period": "2025-04"})[1] == {
        "params.period": "Months from May 2025 only."
    }
    assert ask({"gst_registration_id": reg, "period": "2099-01"})[1] == {
        "params.period": "That month has not started yet."
    }
    assert ask({"period": "2026-10"})[1] == {
        "params.gst_registration_id": "Choose the GST registration."
    }
    with tenant_context(w.t.tenant_id, w.t.user_id):
        GstRegistration.objects.filter(pk=reg).update(registration_type="COMPOSITION")
    status, errors = ask({"gst_registration_id": reg, "period": "2026-10"})
    assert status == 422
    assert "composition files CMP-08" in errors["params.gst_registration_id"]
