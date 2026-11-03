"""Importing catalog items from CSV / XLSX (B.2): sample file, preview, all or nothing."""

import io
import uuid
from typing import Any

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.core.tenancy import tenant_context
from tests.catalog.test_variants import Shop
from tests.factories import add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db

CSV = (
    "Item,Description,UOM,HSN,Price,GST%,Notes\n"  # header aliases; an extra column
    'Wall putty,"White, 40 kg",bag,3214,"₹ 1,250.50",18,keep dry\n'
    "M-sand,,cft,2505,55,5%,\n"
    "Labour - mason,,day,,900,,\n"  # no HSN: allowed; GST defaults to 18
)


class Store(Shop):  # has "OPC 53 cement"
    def upload(
        self, content: bytes | str, member: Any = None, key: str | None = None, **form: Any
    ) -> Any:
        data = content.encode() if isinstance(content, str) else content
        return APIClient().post(
            "/api/v1/catalog-items:import",
            {"file": SimpleUploadedFile("items.csv", data), **form},
            format="multipart",
            **self.h(member, IDEMPOTENCY_KEY=key or str(uuid.uuid4())),
        )

    def names(self) -> list[str]:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            return sorted(CatalogItem.objects.values_list("name", flat=True))


@pytest.fixture
def s() -> Store:
    return Store()


def errors(r: Any) -> list[tuple[str | None, str]]:
    body = r.json()
    return [(e["field"], e["code"]) for e in body.get("errors", [])] or [(None, body["code"])]


def test_check_first_then_import(s: Store) -> None:
    preview = s.upload(CSV, dry_run="true")
    assert preview.status_code == 200, preview.content
    body = preview.json()
    assert body["dry_run"] is True
    assert body["count"] == 3
    assert body["ignored_columns"] == ["Notes"]
    putty = body["items"][0]
    assert (putty["name"], putty["unit"], putty["sac_hsn"]) == ("Wall putty", "bag", "3214")
    assert (putty["default_rate"], putty["gst_rate"], putty["id"]) == ("1250.50", "18.00", None)
    assert body["items"][2]["gst_rate"] == "18.00"
    assert s.names() == ["OPC 53 cement"]  # nothing saved by the check

    done = s.upload(CSV)
    assert done.status_code == 201, done.content
    assert done.json()["count"] == 3
    assert s.names() == ["Labour - mason", "M-sand", "OPC 53 cement", "Wall putty"]


def test_every_bad_row_is_named_and_nothing_is_saved(s: Store) -> None:
    bad = (
        "Item name,HSN/SAC,Rate,GST %\n"
        "opc 53 CEMENT,2523,380,28\n"  # already in the catalog (any case)
        "Bricks,12,8,5\n"  # HSN too short
        "Tiles,6907,abc,18\n"  # not a rate
        "Grout,3824,90,18\n"
        "grout,3824,95,18\n"  # twice in the file
    )
    r = s.upload(bad, dry_run="true")
    assert r.status_code == 422
    assert errors(r) == [
        ("rows[2].name", "item_exists"),
        ("rows[3].sac_hsn", "invalid"),
        ("rows[4].default_rate", "invalid"),
        ("rows[6].name", "duplicate_name"),
    ]
    assert s.upload(bad).status_code == 422
    assert s.names() == ["OPC 53 cement"]


def test_the_sample_file_imports_as_it_is() -> None:
    owner = owner_member(make_tenant("Fresh Co"))
    h: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {owner.access_token}"}
    for fmt in ("xlsx", "csv"):
        sample = APIClient().get("/api/v1/catalog-items:import-sample", {"type": fmt}, **h)
        assert sample.status_code == 200, sample.content
        assert sample["Content-Disposition"] == f'attachment; filename="items-sample.{fmt}"'
        r = APIClient().post(
            "/api/v1/catalog-items:import",
            {"file": SimpleUploadedFile(f"s.{fmt}", sample.content), "dry_run": "true"},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            **h,
        )
        assert r.status_code == 200, r.content
        assert [i["name"] for i in r.json()["items"]] == [
            "OPC 53 cement",
            "River sand",
            "TMT steel bar 12 mm",
        ]
    book = openpyxl.load_workbook(
        io.BytesIO(APIClient().get("/api/v1/catalog-items:import-sample", **h).content)
    )
    assert book.active is not None
    assert [c.value for c in book.active[1]][:3] == ["Item name", "Description", "Unit"]


def test_needs_an_item_name_column(s: Store) -> None:
    r = s.upload("Description,Rate\nSomething,10\n", dry_run="true")
    assert (r.status_code, errors(r)) == (422, [("file", "missing_columns")])


def test_only_roles_that_edit_masters_may_import(s: Store) -> None:
    assert s.upload(CSV, member=add_member(s.t, "SITE_ENGINEER"), dry_run="true").status_code == 403
    assert s.upload(CSV, member=add_member(s.t, "ACCOUNTANT"), dry_run="true").status_code == 200


def test_imports_stay_in_the_tenant(s: Store) -> None:
    other = owner_member(make_tenant("Other Co"))
    # another tenant's "OPC 53 cement" is no conflict, and the rows land in that tenant
    r = APIClient().post(
        "/api/v1/catalog-items:import",
        {"file": SimpleUploadedFile("i.csv", b"Item name\nOPC 53 cement\n")},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        HTTP_AUTHORIZATION=f"Bearer {other.access_token}",
    )
    assert r.status_code == 201, r.content
    assert s.names() == ["OPC 53 cement"]
