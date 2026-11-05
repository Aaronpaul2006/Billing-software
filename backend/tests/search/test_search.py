"""Search for the Ctrl+K command palette (D.6): bills, clients, projects and
catalog items of the caller's business only, a few of each."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import add_client, add_member, make_tenant, owner_member
from tests.payments.test_payments import Money

pytestmark = pytest.mark.django_db


class Shop(Money):
    def __init__(self) -> None:
        super().__init__()
        self.inv = self.invoice()  # INV/0001 for Skyline Developers on VILLA-1
        self.draft = self.create(doc_type="QUOTATION").json()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            CatalogItem.objects.create(name="RCC M25 slab", unit="cum", sac_hsn="9954")
            CatalogItem.objects.create(name="Old cement", is_active=False)

    def search(self, q: str | None, member: Any = None) -> Any:
        return APIClient().get("/api/v1/search", {} if q is None else {"q": q}, **self.h(member))


@pytest.fixture
def s() -> Shop:
    return Shop()


def test_finds_bills_by_number_and_by_client(s: Shop) -> None:
    r = s.search("0001")
    assert r.status_code == 200, r.content
    [doc] = r.json()["documents"]
    assert doc == {
        "id": s.inv["id"],
        "doc_type": "TAX_INVOICE",
        "status": "ISSUED",
        "doc_number": "INV/0001",
        "doc_date": "2026-10-19",
        "party_name": "Skyline Developers",
        "grand_total": "341020.00",  # money stays a string
    }
    by_client = s.search("skyline").json()
    # newest first: the quotation was made after the bill, on the same date
    assert [d["id"] for d in by_client["documents"]] == [s.draft["id"], s.inv["id"]]
    assert [p["display_name"] for p in by_client["parties"]] == ["Skyline Developers"]


def test_finds_projects_and_catalog_items(s: Shop) -> None:
    body = s.search("villa").json()
    assert body["projects"] == [
        {
            "id": str(s.project.pk),
            "code": "VILLA-1",
            "name": "VILLA-1",
            "client_name": "Skyline Developers",
            "status": "ACTIVE",
        }
    ]
    items = s.search("rcc").json()["catalog_items"]
    assert [(i["name"], i["unit"], i["default_rate"]) for i in items] == [
        ("RCC M25 slab", "cum", None)
    ]
    assert [i["name"] for i in s.search("99").json()["catalog_items"]] == ["RCC M25 slab"]
    assert s.search("cement").json()["catalog_items"] == []  # archived items are not offered


def test_a_few_of_each_kind(s: Shop) -> None:
    with tenant_context(s.t.tenant_id, s.t.user_id):
        for i in range(7):
            Party.objects.create(
                display_name=f"Kumar Traders {i}",
                gst_treatment="UNREGISTERED",
                created_by_id=s.t.user_id,
            )
    assert len(s.search("kumar").json()["parties"]) == 5


def test_wildcards_match_only_themselves(s: Shop) -> None:
    body = s.search("%%").json()
    assert body == {"documents": [], "parties": [], "projects": [], "catalog_items": []}
    assert s.search("__").json()["parties"] == []


def test_another_business_sees_nothing(s: Shop) -> None:
    other = make_tenant("Other Builders")
    member = owner_member(other)
    r = APIClient().get(
        "/api/v1/search", {"q": "skyline"}, HTTP_AUTHORIZATION=f"Bearer {member.access_token}"
    )
    assert r.status_code == 200, r.content
    assert r.json() == {"documents": [], "parties": [], "projects": [], "catalog_items": []}


def test_every_staff_role_may_search_but_not_portal_clients(s: Shop) -> None:
    for role in ("SITE_ENGINEER", "VIEWER"):
        r = s.search("skyline", add_member(s.t, role))
        assert r.status_code == 200, (role, r.content)
        assert r.json()["documents"], role
    assert s.search("skyline", add_client(s.t, s.client)).status_code == 403


@pytest.mark.parametrize("q", [None, "", "x", " x ", "x" * 101])
def test_the_query_must_be_2_to_100_characters(s: Shop, q: str | None) -> None:
    r = s.search(q)
    assert r.status_code == 422, r.content
    assert r.json()["errors"][0]["field"] == "q"
