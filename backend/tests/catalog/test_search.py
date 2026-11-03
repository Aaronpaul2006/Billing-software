"""Item search for the bill screen (B.1): `q` and most recently used first."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from tests.catalog.test_variants import Shop
from tests.factories import make_tenant, owner_member

pytestmark = pytest.mark.django_db


class Store(Shop):
    def __init__(self) -> None:
        super().__init__()  # OPC 53 cement (HSN 2523) with brands UltraTech and Local
        self.sand = self.item("River sand", "60.00")
        self.steel = self.item("TMT steel bar", "72.00")

    def names(self, **query: str) -> list[str]:
        r = APIClient().get("/api/v1/catalog-items", query, **self.h())
        assert r.status_code == 200, r.content
        return [row["name"] for row in r.json()["results"]]


@pytest.fixture
def s() -> Store:
    return Store()


def test_search_by_words_of_the_name_any_case(s: Store) -> None:
    assert s.names(q="sand") == ["River sand"]
    assert s.names(q="TMT BAR") == ["TMT steel bar"]  # every word, any order or case
    assert s.names(q="tmt sand") == []


def test_search_by_variant_and_hsn(s: Store) -> None:
    assert s.names(q="ultratech") == ["OPC 53 cement"]
    assert s.names(q="2523", ordering="name") == ["OPC 53 cement", "River sand", "TMT steel bar"]
    assert s.names(q="25", ordering="name")[:1] == ["OPC 53 cement"]


def test_recently_used_items_come_first(s: Store) -> None:
    first = s.create(lines=[{"catalog_item_id": s.steel["id"], "quantity": "10"}])
    assert first.status_code == 201, first.content
    second = s.create(lines=[{"catalog_item_id": s.sand["id"], "quantity": "5"}])
    assert second.status_code == 201, second.content
    recent = {"used": "true", "ordering": "-last_used_at"}
    assert s.names(**recent) == ["River sand", "TMT steel bar"]  # never-used cement left out
    r = APIClient().get("/api/v1/catalog-items", {"ordering": "name"}, **s.h())
    rows: list[dict[str, Any]] = r.json()["results"]
    assert next(x for x in rows if x["name"] == "River sand")["last_used_at"] is not None
    assert next(x for x in rows if x["name"] == "OPC 53 cement")["last_used_at"] is None


def test_another_tenants_items_are_not_found() -> None:
    a, b = Store(), owner_member(make_tenant("Other"))
    assert a.names(q="sand") == ["River sand"]
    r = APIClient().get(
        "/api/v1/catalog-items", {"q": "sand"}, HTTP_AUTHORIZATION=f"Bearer {b.access_token}"
    )
    assert r.json()["results"] == []
