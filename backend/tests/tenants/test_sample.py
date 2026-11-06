"""A sample business to explore with (Part B): a separate business, filled
with sample work, never touching the real one; closed in one step."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.diary.models import DiaryEntry
from apps.documents.models import Document
from apps.payables.models import VendorBill
from apps.payments.models import Payment
from apps.tenants.models import DocumentSeries, Tenant
from tests.factories import add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db


def h(member: Any) -> dict[str, Any]:
    return {"HTTP_AUTHORIZATION": f"Bearer {member.access_token}"}


def test_ask_get_switch_and_remove(django_capture_on_commit_callbacks: Any) -> None:
    t = make_tenant()
    owner = owner_member(t)
    with tenant_context(t.tenant_id, t.user_id):
        real_series = list(DocumentSeries.objects.values_list("next_number", flat=True))
        real_docs = Document.objects.count()

    assert APIClient().get("/api/v1/sample-business", **h(owner)).json()["status"] == "NONE"
    with django_capture_on_commit_callbacks(execute=True):
        r = APIClient().post("/api/v1/sample-business", **h(owner))
    assert (r.status_code, r.json()["status"]) == (202, "MAKING")
    ready = APIClient().get("/api/v1/sample-business", **h(owner)).json()
    assert ready["status"] == "READY"
    assert ready["legal_name"].startswith("Sample:")
    sample_id = ready["tenant_id"]
    again = APIClient().post("/api/v1/sample-business", **h(owner))
    assert (again.status_code, again.json()["tenant_id"]) == (200, sample_id)  # one at a time

    # what is in it: issued RA bills, a payment, a quotation, a vendor bill, diary days
    with tenant_context(sample_id, t.user_id):
        assert Tenant.objects.get(pk=sample_id).is_sample
        issued = Document.objects.filter(status="ISSUED")
        assert sorted(issued.values_list("doc_type", flat=True)) == [
            "QUOTATION",
            "TAX_INVOICE",
            "TAX_INVOICE",
        ]
        assert issued.filter(is_ra_bill=True).count() == 2
        assert Payment.objects.count() == 1
        assert VendorBill.objects.count() == 1
        assert DiaryEntry.objects.count() == 2
    # the real business is untouched: same documents, same numbering
    with tenant_context(t.tenant_id, t.user_id):
        assert Document.objects.count() == real_docs
        assert list(DocumentSeries.objects.values_list("next_number", flat=True)) == real_series

    # switch to it, see it is a sample, remove it
    r = APIClient().post(
        "/api/v1/auth/switch-tenant", {"tenant_id": sample_id}, format="json", **h(owner)
    )
    assert r.status_code == 200, r.content
    token = r.json()["access_token"]
    inside: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    assert APIClient().get("/api/v1/tenant", **inside).json()["is_sample"] is True
    assert APIClient().post("/api/v1/sample-business/remove", **inside).status_code == 204
    # back to the real business (as the web does after removing it)
    r = APIClient().post(
        "/api/v1/auth/switch-tenant", {"tenant_id": str(t.tenant_id)}, format="json", **inside
    )
    assert r.status_code == 200, r.content
    back: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access_token']}"}
    assert APIClient().get("/api/v1/sample-business", **back).json()["status"] == "NONE"
    r = APIClient().post(
        "/api/v1/auth/switch-tenant", {"tenant_id": sample_id}, format="json", **back
    )
    assert r.status_code in (403, 404)  # closed: no longer one of theirs


def test_a_real_business_is_not_removed_this_way() -> None:
    t = make_tenant()
    r = APIClient().post("/api/v1/sample-business/remove", **h(owner_member(t)))
    assert (r.status_code, r.json()["code"]) == (409, "not_a_sample")
    with tenant_context(t.tenant_id, t.user_id):
        assert Tenant.objects.get(pk=t.tenant_id).status == "ACTIVE"


def test_each_person_gets_their_own(django_capture_on_commit_callbacks: Any) -> None:
    t = make_tenant()
    owner, accountant = owner_member(t), add_member(t, "ACCOUNTANT")
    with django_capture_on_commit_callbacks(execute=True):
        APIClient().post("/api/v1/sample-business", **h(owner))
    assert APIClient().get("/api/v1/sample-business", **h(accountant)).json()["status"] == "NONE"
