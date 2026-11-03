"""Importing clients from CSV / XLSX (B.3): plain columns, preview, all or nothing."""

import uuid
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import add_member, gstin, make_party, make_tenant, owner_member

pytestmark = pytest.mark.django_db

SKYLINE = gstin("32", pan="AAACS4321K")
CSV = (
    "Client Name,GSTIN,GST Type,State,Mobile,Email,Address,City,PIN\n"
    f"Skyline Developers,{SKYLINE},,,98470 12345,accounts@skyline.example,MG Road,Kochi,682016\n"
    "Anna Kurian,,Consumer,kerala,,,,,\n"
    "Coastal Homes,,,33,,,,,\n"
)


class Office:
    def __init__(self) -> None:
        self.t = make_tenant("Nair Constructions")
        self.owner = owner_member(self.t)
        make_party(self.t, "Existing Client")

    def upload(self, content: str, member: Any = None, key: str | None = None, **form: Any) -> Any:
        m = member or self.owner
        return APIClient().post(
            "/api/v1/parties:import",
            {"file": SimpleUploadedFile("clients.csv", content.encode()), **form},
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {m.access_token}",
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )

    def parties(self) -> dict[str, Party]:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            return {p.display_name: p for p in Party.objects.all()}


@pytest.fixture
def o() -> Office:
    return Office()


def errors(r: Any) -> list[tuple[str | None, str]]:
    body = r.json()
    return [(e["field"], e["code"]) for e in body.get("errors", [])] or [(None, body["code"])]


def test_plain_columns_become_clients(o: Office) -> None:
    preview = o.upload(CSV, dry_run="true")
    assert preview.status_code == 200, preview.content
    assert preview.json()["count"] == 3
    assert set(o.parties()) == {"Existing Client"}  # the check saves nothing

    r = o.upload(CSV)
    assert r.status_code == 201, r.content
    saved = o.parties()
    skyline = saved["Skyline Developers"]
    # a GSTIN means registered; state and PAN are read from it
    assert (skyline.gst_treatment, skyline.state_code, skyline.pan) == (
        "REGISTERED",
        "32",
        "AAACS4321K",
    )
    assert skyline.phone == "9847012345"
    assert skyline.billing_address == {
        "line1": "MG Road",
        "city": "Kochi",
        "pincode": "682016",
        "state_code": "32",
        "country": "IN",
    }
    anna = saved["Anna Kurian"]
    assert (anna.gst_treatment, anna.state_code, anna.gstin) == ("CONSUMER", "32", None)
    assert (saved["Coastal Homes"].gst_treatment, saved["Coastal Homes"].state_code) == (
        "UNREGISTERED",
        "33",
    )
    assert all(p.is_customer for p in saved.values())


def test_every_bad_row_is_named(o: Office) -> None:
    bad = (
        "Name,GSTIN,GST type,State\n"
        "existing CLIENT,,,Kerala\n"  # already a client (any case)
        "Bad GSTIN Co,32AAACS4321K1Z1,,\n"  # wrong check digit
        "Nowhere Ltd,,,Atlantis\n"  # no such state
        "Composition Co,,Composition,Kerala\n"  # composition needs a GSTIN
        f"Twin One,{SKYLINE},,\n"
        f"Twin Two,{SKYLINE},,\n"  # the same GSTIN twice in the file
    )
    r = o.upload(bad, dry_run="true")
    assert r.status_code == 422
    assert errors(r) == [
        ("rows[2].display_name", "party_exists"),
        ("rows[3].gstin", "invalid_gstin"),
        ("rows[4].state_code", "invalid_choice"),
        ("rows[5].gstin", "required"),
        ("rows[7].gstin", "duplicate_gstin"),
    ]
    assert set(o.parties()) == {"Existing Client"}


def test_the_sample_file_imports_as_it_is() -> None:
    o = Office()
    h: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {o.owner.access_token}"}
    for fmt in ("xlsx", "csv"):
        sample = APIClient().get("/api/v1/parties:import-sample", {"type": fmt}, **h)
        assert sample.status_code == 200
        r = APIClient().post(
            "/api/v1/parties:import",
            {"file": SimpleUploadedFile(f"s.{fmt}", sample.content), "dry_run": "true"},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            **h,
        )
        assert r.status_code == 200, r.content
        assert [p["display_name"] for p in r.json()["parties"]] == [
            "Skyline Developers",
            "Anna Kurian",
            "Coastal Homes",
        ]


def test_only_roles_that_edit_masters_may_import(o: Office) -> None:
    viewer = add_member(o.t, "VIEWER")
    assert o.upload(CSV, member=viewer, dry_run="true").status_code == 403


def test_imports_stay_in_the_tenant(o: Office) -> None:
    other = Office()  # also has an "Existing Client": no conflict across tenants
    r = other.upload("Name\nNew Client\n")
    assert r.status_code == 201, r.content
    assert "New Client" not in o.parties()
    stranger = owner_member(make_tenant("Stranger"))
    r = o.upload("Name\nExisting Client\n", member=stranger)
    assert r.status_code == 201, r.content  # the stranger's own tenant had no such client
