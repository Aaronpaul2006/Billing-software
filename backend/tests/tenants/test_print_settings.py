"""Print settings: logo, signature, bank details, UPI ID, default terms, layout (B.12)."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.files.models import Attachment
from tests.documents.test_drafts import World
from tests.factories import add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db

URL = "/api/v1/tenant/print-settings"

BANK = {
    "bank_account_name": "Nair Constructions",
    "bank_name": "State Bank of India",
    "bank_account_number": "3012 3456 7890",
    "bank_ifsc": "sbin0070123",
    "bank_branch": "Kakkanad",
    "upi_id": "nairconstructions@okaxis",
}


@pytest.fixture
def w() -> World:
    return World()


def image(
    w: World,
    content_type: str = "image/png",
    size: int = 20_000,
    status: str = "AVAILABLE",
    tenant: Any = None,
) -> str:
    t = tenant or w.t
    with tenant_context(t.tenant_id, t.user_id):
        a = Attachment.objects.create(
            storage_key=f"tenants/{t.tenant_id}/uploads/{uuid.uuid4()}.png",
            original_filename="logo.png",
            content_type=content_type,
            size_bytes=size,
            status=status,
            uploaded_by_id=t.user_id,
        )
    return str(a.pk)


def patch(w: World, body: dict[str, Any], version: int = 1, member: Any = None) -> Any:
    return APIClient().patch(URL, body, format="json", **w.h(member, IF_MATCH=f'"v{version}"'))


def problem(r: Any) -> tuple[int, str]:
    b = r.json()
    return r.status_code, (b["errors"][0]["code"] if b["code"] == "validation_error" else b["code"])


def test_defaults_before_the_first_save(w: World) -> None:
    r = APIClient().get(URL, **w.h())
    assert r.status_code == 200, r.content
    assert r.headers["ETag"] == '"v1"'
    assert r.json() == {
        "layout": "DETAILED",
        "logo_attachment_id": None,
        "signature_attachment_id": None,
        "bank_account_name": None,
        "bank_name": None,
        "bank_account_number": None,
        "bank_ifsc": None,
        "bank_branch": None,
        "upi_id": None,
        "default_terms": None,
        "version": 1,
    }


def test_save_bank_details_upi_logo_and_layout(w: World) -> None:
    logo, sign = image(w), image(w, "image/jpeg")
    r = patch(
        w,
        {
            **BANK,
            "layout": "SIMPLE",
            "logo_attachment_id": logo,
            "signature_attachment_id": sign,
            "default_terms": "  Payment within 15 days.\nInterest at 18% after that.  ",
        },
    )
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["version"] == 2
    assert (body["bank_account_number"], body["bank_ifsc"]) == ("301234567890", "SBIN0070123")
    assert (body["logo_attachment_id"], body["signature_attachment_id"]) == (logo, sign)
    assert body["default_terms"] == "Payment within 15 days.\nInterest at 18% after that."
    # a later save: only what is sent changes; blank clears
    r = patch(w, {"upi_id": "", "layout": "DETAILED"}, version=2)
    assert r.status_code == 200, r.content
    assert (r.json()["upi_id"], r.json()["layout"], r.json()["bank_name"]) == (
        None,
        "DETAILED",
        "State Bank of India",
    )
    assert patch(w, {"layout": "SIMPLE"}, version=2).status_code == 412


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("bank_ifsc", "SBIN1070123", "invalid_ifsc"),
        ("bank_account_number", "12AB45", "invalid_account_number"),
        ("upi_id", "nair constructions", "invalid_upi_id"),
        ("layout", "FANCY", "invalid_choice"),
    ],
)
def test_wrong_details_are_refused_in_plain_words(
    w: World, field: str, value: str, code: str
) -> None:
    assert problem(patch(w, {field: value})) == (422, code)


def test_logo_must_be_a_small_checked_image_of_this_business(w: World) -> None:
    pdf = image(w, "application/pdf")
    big = image(w, size=2 * 1024 * 1024)
    pending = image(w, status="PENDING")
    other = make_tenant("Stranger Co")
    theirs = image(w, tenant=other)
    assert problem(patch(w, {"logo_attachment_id": pdf})) == (422, "not_an_image")
    assert problem(patch(w, {"logo_attachment_id": big})) == (422, "image_too_large")
    assert problem(patch(w, {"signature_attachment_id": pending})) == (422, "not_available")
    assert problem(patch(w, {"logo_attachment_id": theirs}))[0] == 422  # as if it did not exist


def test_everyone_reads_owners_and_admins_change(w: World) -> None:
    viewer = add_member(w.t, "VIEWER")
    accountant = add_member(w.t, "ACCOUNTANT")
    admin = add_member(w.t, "ADMIN")
    assert APIClient().get(URL, **w.h(viewer)).status_code == 200
    assert patch(w, {"layout": "SIMPLE"}, member=accountant).status_code == 403
    assert patch(w, {"layout": "SIMPLE"}, member=admin).status_code == 200


def test_another_business_sees_only_its_own(w: World) -> None:
    assert patch(w, BANK).status_code == 200
    stranger = owner_member(make_tenant("Stranger Co"))
    r = APIClient().get(URL, **w.h(stranger))
    assert (r.status_code, r.json()["bank_name"]) == (200, None)


def test_new_bills_get_the_default_terms(w: World) -> None:
    assert patch(w, {"default_terms": "Payment within 15 days."}).status_code == 200
    assert w.create().json()["terms"] == "Payment within 15 days."
    assert w.create(doc_type="QUOTATION").json()["terms"] == "Payment within 15 days."
    assert w.create(terms=None).json()["terms"] is None  # said otherwise
    assert w.create(terms="Advance 50%").json()["terms"] == "Advance 50%"
