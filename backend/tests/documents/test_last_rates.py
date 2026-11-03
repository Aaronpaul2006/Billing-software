"""The rate last charged to a client per catalog item (B.8)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from apps.tenants.models import DocumentSeries
from tests.catalog.test_variants import Shop
from tests.factories import make_tenant, owner_member

pytestmark = pytest.mark.django_db


class Counter(Shop):  # OPC 53 cement at 380.00, with UltraTech (+20) and Local (-15)
    def __init__(self) -> None:
        super().__init__()
        with tenant_context(self.t.tenant_id, self.t.user_id):
            for doc_type, prefix in (("TAX_INVOICE", "INV/"), ("QUOTATION", "QT/")):
                DocumentSeries.objects.create(
                    gst_registration_id=self.t.registration_id,
                    doc_type=doc_type,
                    fy_start_year=2026,
                    prefix=prefix,
                )

    def bill(self, *lines: dict[str, Any], issue: bool = True, **header: Any) -> dict[str, Any]:
        r = self.create(lines=list(lines), **header)
        assert r.status_code == 201, r.content
        draft = dict(r.json())
        if not issue:
            return draft
        r = APIClient().post(
            f"/api/v1/documents/{draft['id']}/issue",
            {},
            format="json",
            **self.h(IF_MATCH='"v1"', IDEMPOTENCY_KEY=str(uuid.uuid4())),
        )
        assert r.status_code == 200, r.content
        return dict(r.json())

    def rates(self, party: Any = None, member: Any = None) -> Any:
        pk = (party or self.client).pk
        return APIClient().get(f"/api/v1/parties/{pk}/last-rates", **self.h(member))


@pytest.fixture
def c() -> Counter:
    return Counter()


def test_the_latest_issued_bill_per_item_and_variant(c: Counter) -> None:
    cement = c.cement["id"]
    first = c.bill(
        c.line(rate="380.00"),
        c.line(catalog_variant_id=c.ultratech["id"], rate="410.00"),
        doc_date="2026-10-01",
    )
    second = c.bill(c.line(rate="395.00"), doc_date="2026-10-15")
    c.bill(c.line(rate="999.00"), doc_date="2026-10-20", issue=False)  # a draft: not charged
    c.bill(c.line(rate="300.00"), doc_type="QUOTATION", doc_date="2026-10-21")  # quoted only
    with tenant_context(c.t.tenant_id, c.t.user_id):
        other = Party.objects.create(
            display_name="Other Client",
            gst_treatment="UNREGISTERED",
            state_code="32",
            created_by_id=c.t.user_id,
        )
    c.bill(c.line(rate="500.00"), party_id=str(other.pk), project_id=None, doc_date="2026-10-22")

    r = c.rates()
    assert r.status_code == 200, r.content
    got = {(x["catalog_item_id"], x["catalog_variant_id"]): x for x in r.json()["results"]}
    assert set(got) == {(cement, None), (cement, c.ultratech["id"])}
    plain = got[(cement, None)]
    assert (plain["rate"], plain["doc_number"], plain["doc_date"]) == (
        "395.00",
        second["doc_number"],
        "2026-10-15",
    )
    assert got[(cement, c.ultratech["id"])]["rate"] == "410.00"
    assert got[(cement, c.ultratech["id"])]["document_id"] == first["id"]
    other_rates = c.rates(party=other).json()["results"]
    assert [x["rate"] for x in other_rates] == ["500.00"]


def test_a_new_client_has_none(c: Counter) -> None:
    assert c.rates().json() == {"results": []}


def test_another_tenants_client_is_not_found(c: Counter) -> None:
    stranger = owner_member(make_tenant("Stranger Co"))
    assert c.rates(member=stranger).status_code == 404
