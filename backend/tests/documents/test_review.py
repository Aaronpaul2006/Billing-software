"""The last look before issuing: warnings, never a block (B.14)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.documents.test_drafts import RCC
from tests.factories import add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db


@pytest.fixture
def m() -> Money:
    return Money()


def review(m: Money, doc: dict[str, Any], member: Any = None) -> Any:
    return APIClient().get(f"/api/v1/documents/{doc['id']}/review", **m.h(member))


def codes(m: Money, doc: dict[str, Any]) -> list[str]:
    r = review(m, doc)
    assert r.status_code == 200, r.content
    return [w["code"] for w in r.json()["warnings"]]


def test_a_clean_draft_has_nothing_to_say(m: Money) -> None:
    draft = m.create(due_date="2026-11-18").json()
    assert codes(m, draft) == []


def test_no_due_date_and_missing_hsn(m: Money) -> None:
    draft = m.create(lines=[RCC, {**RCC, "description": "Extra work", "sac_hsn": None}]).json()
    r = review(m, draft).json()["warnings"]
    assert [(w["code"], w["line_no"]) for w in r] == [
        ("no_due_date", None),
        ("missing_hsn", 2),
    ]
    assert r[1]["message"].startswith('Line 2 "Extra work" has no HSN / SAC code')


def test_client_without_gstin_and_a_business_pan(m: Money) -> None:
    with tenant_context(m.t.tenant_id, m.t.user_id):
        shop = Party.objects.create(
            display_name="Lakshmi Traders",
            gst_treatment="UNREGISTERED",
            pan="AAAFL1234K",  # F: a firm
            state_code="32",
            created_by_id=m.t.user_id,
        )
        person = Party.objects.create(
            display_name="Anil Kumar",
            gst_treatment="UNREGISTERED",
            pan="ABCPK1234L",  # P: a person
            state_code="32",
            created_by_id=m.t.user_id,
        )
    firm_bill = m.create(party_id=str(shop.pk), project_id=None, due_date="2026-11-18").json()
    w = review(m, firm_bill).json()["warnings"]
    assert [x["code"] for x in w] == ["client_no_gstin"]
    assert "probably registered" in w[0]["message"]
    own = m.create(party_id=str(person.pk), project_id=None, due_date="2026-11-18").json()
    w = review(m, own).json()["warnings"]
    assert [x["code"] for x in w] == ["client_no_gstin"]
    assert "probably registered" not in w[0]["message"]
    # a quotation is not a GST bill: nothing to say about the GSTIN
    quote = m.create(party_id=str(shop.pk), project_id=None, doc_type="QUOTATION").json()
    assert "client_no_gstin" not in codes(m, quote)


def test_possible_duplicate_same_client_total_within_1_percent_last_7_days(m: Money) -> None:
    first = m.invoice(doc_date="2026-10-15", due_date="2026-11-18")
    near = m.create(
        doc_date="2026-10-19", due_date="2026-11-18", lines=[{**RCC, "rate": "6830.00"}]
    ).json()  # +0.44 %
    w = review(m, near).json()["warnings"]
    assert [x["code"] for x in w] == ["possible_duplicate"]
    assert w[0]["message"].startswith(f"{first['doc_number']} dated 15-10-2026")
    far = m.create(
        doc_date="2026-10-19", due_date="2026-11-18", lines=[{**RCC, "rate": "7000.00"}]
    ).json()  # +2.9 %
    assert codes(m, far) == []
    later = m.create(doc_date="2026-10-30", due_date="2026-11-18").json()  # 15 days on
    assert codes(m, later) == []


def test_rate_far_below_the_usual_rate(m: Money) -> None:
    with tenant_context(m.t.tenant_id, m.t.user_id):
        item = CatalogItem.objects.create(
            name="Plastering", unit="sqm", sac_hsn="9954", default_rate=Decimal("310.00")
        )
    line = {
        "catalog_item_id": str(item.pk),
        "description": "Plastering",
        "sac_hsn": "9954",
        "unit": "sqm",
        "quantity": "100",
        "gst_rate": "18.00",
    }
    low = m.create(due_date="2026-11-18", lines=[{**line, "rate": "31.00"}]).json()  # a slip
    w = review(m, low).json()["warnings"]
    assert [(x["code"], x["line_no"]) for x in w] == [("rate_below_usual", 1)]
    assert "₹31.00 is far below the usual ₹310.00" in w[0]["message"]
    fine = m.create(due_date="2026-11-18", lines=[{**line, "rate": "290.00"}]).json()
    assert codes(m, fine) == []
    # once billed to this client at 200, that is the usual rate for them
    m.invoice(due_date="2026-11-18", lines=[{**line, "rate": "200.00"}])
    again = m.create(due_date="2026-11-18", lines=[{**line, "rate": "180.00"}]).json()
    assert "rate_below_usual" not in codes(m, again)


def test_no_number_series_and_issued_bills_need_no_review(m: Money) -> None:
    proforma = m.create(doc_type="PROFORMA", due_date="2026-11-18").json()
    w = review(m, proforma).json()["warnings"]
    assert [x["code"] for x in w] == ["no_number_series"]
    assert "financial year 2026-27" in w[0]["message"]
    bill = m.invoice()
    assert codes(m, bill) == []
    # warnings never block: a bill with warnings still issues
    draft = m.create().json()
    assert "no_due_date" in codes(m, draft)
    r = APIClient().post(
        f"/api/v1/documents/{draft['id']}/issue",
        {},
        format="json",
        **m.h(IF_MATCH='"v1"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
    )
    assert r.status_code == 200, r.content


def test_everyone_who_can_see_the_bill_and_another_tenant(m: Money) -> None:
    draft = m.create().json()
    assert review(m, draft, member=add_member(m.t, "VIEWER")).status_code == 200


def test_another_tenants_bill_is_not_found(m: Money) -> None:
    draft = m.create().json()
    stranger = owner_member(make_tenant("Stranger Co"))
    assert review(m, draft, member=stranger).status_code == 404
