"""Proof of work (Part B): diary photos chosen for a bill, seen in the portal."""

import uuid
from datetime import date
from typing import Any

import pytest
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.diary.models import DiaryEntry, DiaryPhoto, DocumentPhoto
from apps.files.models import Attachment
from apps.projects.models import Project
from tests.portal.test_portal import Portal

pytestmark = pytest.mark.django_db


def photo(p: Portal, project: Project, day: int, caption: str) -> str:
    with tenant_context(p.t.tenant_id, p.t.user_id):
        entry, _ = DiaryEntry.objects.get_or_create(
            project=project,
            entry_date=date(2026, 10, day),
            defaults={"work_done": "Slab", "created_by_id": p.t.user_id},
        )
        a = Attachment.objects.create(
            storage_key=f"t/{uuid.uuid4()}",
            original_filename="site.jpg",
            content_type="image/jpeg",
            size_bytes=1000,
            status="AVAILABLE",
            uploaded_by_id=p.t.user_id,
        )
        ph = DiaryPhoto.objects.create(
            entry=entry, attachment=a, caption=caption, created_by_id=p.t.user_id
        )
    return str(ph.pk)


def choose(p: Portal, doc_id: str, ids: list[str], member: Any = None) -> Any:
    return APIClient().put(
        f"/api/v1/documents/{doc_id}/photos",
        {"diary_photo_ids": ids},
        format="json",
        **p.h(member),
    )


@pytest.fixture
def p() -> Portal:
    return Portal()


def test_choose_photos_for_a_bill_and_the_client_sees_them(p: Portal) -> None:
    first = photo(p, p.project, 15, "Slab shuttering")
    second = photo(p, p.project, 17, "Concreting")
    r = choose(p, p.inv1["id"], [second, first])
    assert r.status_code == 200, r.content
    assert [x["caption"] for x in r.json()["results"]] == ["Concreting", "Slab shuttering"]
    assert r.json()["results"][0]["entry_date"] == "2026-10-17"
    staff = APIClient().get(f"/api/v1/documents/{p.inv1['id']}/photos", **p.h()).json()
    assert [x["id"] for x in staff["results"]] == [second, first]

    seen = APIClient().get(f"/api/v1/portal/documents/{p.inv1['id']}/photos", **p.h(p.me))
    assert seen.status_code == 200, seen.content
    assert [x["caption"] for x in seen.json()["results"]] == ["Concreting", "Slab shuttering"]
    assert seen.json()["results"][0]["url"].startswith("http")
    # the client sees nothing else of the diary
    other = APIClient().get(f"/api/v1/portal/documents/{p.inv2['id']}/photos", **p.h(p.me))
    assert other.json()["results"] == []

    assert choose(p, p.inv1["id"], []).json()["results"] == []
    seen = APIClient().get(f"/api/v1/portal/documents/{p.inv1['id']}/photos", **p.h(p.me))
    assert seen.json()["results"] == []


def test_only_photos_of_the_bills_project(p: Portal) -> None:
    elsewhere = photo(p, p.other_project, 15, "Other site")
    r = choose(p, p.inv1["id"], [elsewhere])
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "not_found")
    with (
        tenant_context(p.t.tenant_id, p.t.user_id),
        pytest.raises(DatabaseError),
        transaction.atomic(),
    ):
        DocumentPhoto.objects.create(
            document_id=p.inv1["id"], diary_photo_id=elsewhere, created_by_id=p.t.user_id
        )
    mine = photo(p, p.project, 15, "Ours")
    assert choose(p, p.inv1["id"], [mine, mine]).status_code == 422  # twice
    assert choose(p, p.inv1["id"], [mine]).status_code == 200
    # removing the photo from the diary takes it off the bill
    with tenant_context(p.t.tenant_id, p.t.user_id):
        DiaryPhoto.objects.filter(pk=mine).delete()
        assert DocumentPhoto.objects.count() == 0


def test_a_draft_with_photos_can_still_be_deleted(p: Portal) -> None:
    assert choose(p, p.draft["id"], [photo(p, p.project, 15, "Slab")]).status_code == 200
    r = APIClient().delete(
        f"/api/v1/documents/{p.draft['id']}", **p.h(IF_MATCH=f'"v{p.draft["version"]}"')
    )
    assert r.status_code == 204, r.content
    with tenant_context(p.t.tenant_id, p.t.user_id):
        assert DocumentPhoto.objects.count() == 0
        assert DiaryPhoto.objects.count() == 1  # the diary keeps its photo


def test_another_business_and_another_client_see_none(p: Portal) -> None:
    choose(p, p.inv1["id"], [photo(p, p.project, 15, "Slab")])
    # the client cannot see another client's bill, nor its photos
    r = APIClient().get(f"/api/v1/portal/documents/{p.others_bill['id']}/photos", **p.h(p.me))
    assert r.status_code == 404
    other = Portal()
    for url in (f"/api/v1/documents/{p.inv1['id']}/photos",):
        assert APIClient().get(url, **other.h()).status_code == 404
    assert choose(other, p.inv1["id"], []).status_code == 404
    r = APIClient().get(f"/api/v1/portal/documents/{p.inv1['id']}/photos", **other.h(other.me))
    assert r.status_code == 404


def test_the_bill_pdf_gets_a_page_of_site_photos(p: Portal, monkeypatch: Any) -> None:
    from apps.documents.models import Document
    from apps.documents.pdf.render import render_html

    first = photo(p, p.project, 15, "Slab shuttering")
    broken = photo(p, p.project, 16, "Unreadable")
    with tenant_context(p.t.tenant_id, p.t.user_id):
        bad_key = (
            DiaryPhoto.objects.select_related("attachment").get(pk=broken).attachment.storage_key
        )

    def fake_get(key: str) -> bytes:
        if key == bad_key:
            raise OSError("gone")
        return bytes([0xFF, 0xD8, 0xFF]) + b"-jpeg"

    monkeypatch.setattr("apps.files.storage.get", fake_get)
    assert choose(p, p.inv1["id"], [first, broken]).status_code == 200
    with tenant_context(p.t.tenant_id, p.t.user_id):
        html = render_html(Document.objects.get(pk=p.inv1["id"]))
    assert '<section class="photos">' in html
    assert "Slab shuttering" in html
    assert "15 Oct 2026" in html
    assert html.count("data:image/jpeg;base64,") == 1  # the unreadable one is left out
    with tenant_context(p.t.tenant_id, p.t.user_id):
        plain = render_html(Document.objects.get(pk=p.inv2["id"]))
    assert '<section class="photos">' not in plain


def test_changing_the_photos_makes_the_pdf_again(
    p: Portal, django_capture_on_commit_callbacks: Any
) -> None:
    from apps.documents.models import Document

    with tenant_context(p.t.tenant_id, p.t.user_id):
        a = Attachment.objects.create(
            storage_key=f"t/{uuid.uuid4()}",
            original_filename="inv.pdf",
            content_type="application/pdf",
            size_bytes=1000,
            status="AVAILABLE",
            uploaded_by_id=p.t.user_id,
        )
        Document.objects.filter(pk=p.inv1["id"]).update(pdf_attachment_id=a.pk)
    with django_capture_on_commit_callbacks(execute=False) as queued:
        assert choose(p, p.inv1["id"], [photo(p, p.project, 15, "Slab")]).status_code == 200
    assert len(queued) == 1  # the new PDF, once the choice is saved
    with tenant_context(p.t.tenant_id, p.t.user_id):
        assert Document.objects.get(pk=p.inv1["id"]).pdf_attachment_id is None
