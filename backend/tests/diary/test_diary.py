"""Site diary (Part B): one entry per project and day, with photos."""

import uuid
from datetime import date
from typing import Any

import pytest
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.diary.models import DiaryEntry, DiaryPhoto
from apps.files.models import Attachment
from apps.parties.models import Party
from apps.projects.models import Project
from tests.factories import Member, add_member, make_tenant, owner_member

pytestmark = pytest.mark.django_db


class Site:
    def __init__(self, name: str = "Nair Constructions") -> None:
        self.t = make_tenant(name)
        self.owner = owner_member(self.t)
        self.engineer = add_member(self.t, "SITE_ENGINEER")
        with tenant_context(self.t.tenant_id, self.t.user_id):
            client = Party.objects.create(
                display_name="Skyline Developers",
                gst_treatment="UNREGISTERED",
                created_by_id=self.t.user_id,
            )
            self.project = Project.objects.create(
                code="VILLA-1",
                name="Villa",
                client_party=client,
                gst_registration_id=self.t.registration_id,
                site_state_code="32",
                created_by_id=self.t.user_id,
            )

    def file(self, content_type: str = "image/jpeg", status: str = "AVAILABLE") -> str:
        with tenant_context(self.t.tenant_id, self.t.user_id):
            a = Attachment.objects.create(
                storage_key=f"t/{uuid.uuid4()}",
                original_filename="site.jpg",
                content_type=content_type,
                size_bytes=1000,
                status=status,
                uploaded_by_id=self.t.user_id,
            )
        return str(a.pk)

    def call(
        self, method: str, url: str, body: Any = None, member: Member | None = None, **headers: str
    ) -> Any:
        m = member or self.engineer
        h = {
            "HTTP_AUTHORIZATION": f"Bearer {m.access_token}",
            "HTTP_IDEMPOTENCY_KEY": str(uuid.uuid4()),
        }
        h.update({f"HTTP_{k}": v for k, v in headers.items()})
        return getattr(APIClient(), method)(f"/api/v1/{url}", body, format="json", **h)

    def day(self, on: str = "2026-11-05", member: Member | None = None, **body: Any) -> Any:
        return self.call(
            "post",
            f"projects/{self.project.pk}/diary",
            {"entry_date": on, "work_done": "First floor slab shuttering", **body},
            member,
        )


@pytest.fixture
def s() -> Site:
    return Site()


def code(r: Any) -> str:
    body = r.json()
    return str(body["errors"][0]["code"] if body["code"] == "validation_error" else body["code"])


def test_a_day_with_photos(s: Site) -> None:
    r = s.day(
        weather="RAIN",
        workers=14,
        hold_ups="Rain from 2 pm; concreting moved to tomorrow",
        photos=[
            {"attachment_id": s.file(), "caption": "Shuttering, grid B"},
            {"attachment_id": s.file()},
        ],
    )
    assert r.status_code == 201, r.content
    entry = r.json()
    assert (entry["weather"], entry["workers"], len(entry["photos"])) == ("RAIN", 14, 2)
    assert entry["photos"][0]["caption"] == "Shuttering, grid B"
    assert entry["photos"][0]["url"].startswith("http")

    again = s.day()
    assert (again.status_code, code(again)) == (409, "entry_exists")
    assert again.json()["entry_id"] == entry["id"]

    r = s.call(
        "patch", f"diary-entries/{entry['id']}", {"work_done": "Shuttering done"}, IF_MATCH='"v1"'
    )
    assert r.json()["work_done"] == "Shuttering done"
    r = s.call(
        "post",
        f"diary-entries/{entry['id']}/photos",
        {"photos": [{"attachment_id": s.file(content_type="image/png")}]},
    )
    assert len(r.json()["photos"]) == 3
    gone = r.json()["photos"][0]["id"]
    assert s.call("delete", f"diary-photos/{gone}").status_code == 204
    assert len(s.call("get", f"diary-entries/{entry['id']}").json()["photos"]) == 2


def test_newest_first_and_by_dates(s: Site) -> None:
    for on in ("2026-11-03", "2026-11-05", "2026-11-04"):
        assert s.day(on).status_code == 201
    days = s.call("get", f"projects/{s.project.pk}/diary").json()["results"]
    assert [d["entry_date"] for d in days] == ["2026-11-05", "2026-11-04", "2026-11-03"]
    some = s.call("get", f"projects/{s.project.pk}/diary?date_from=2026-11-04&date_to=2026-11-04")
    assert [d["entry_date"] for d in some.json()["results"]] == ["2026-11-04"]


def test_only_checked_photos(s: Site) -> None:
    r = s.day(photos=[{"attachment_id": s.file(content_type="application/pdf")}])
    assert (r.status_code, code(r)) == (422, "not_a_photo")
    r = s.day(photos=[{"attachment_id": s.file(status="PENDING")}])
    assert (r.status_code, code(r)) == (422, "not_available")
    # the database refuses them too
    entry = s.day().json()
    with tenant_context(s.t.tenant_id, s.t.user_id):
        with pytest.raises(DatabaseError), transaction.atomic():
            DiaryPhoto.objects.create(
                entry_id=entry["id"],
                attachment_id=s.file(content_type="application/pdf"),
                created_by_id=s.t.user_id,
            )
        with pytest.raises(DatabaseError), transaction.atomic():
            DiaryEntry.objects.create(  # the same day twice
                project=s.project,
                entry_date=date(2026, 11, 5),
                work_done="x",
                created_by_id=s.t.user_id,
            )


def test_who_may(s: Site) -> None:
    viewer = add_member(s.t, "VIEWER")
    assert s.day(member=viewer).status_code == 403
    assert s.day().status_code == 201  # a site engineer writes it
    assert s.call("get", f"projects/{s.project.pk}/diary", member=viewer).status_code == 200


def test_another_business_reaches_none_of_it(s: Site) -> None:
    entry = s.day(photos=[{"attachment_id": s.file()}]).json()
    other = Site("Other Builders")
    for method, url in (
        ("get", f"projects/{s.project.pk}/diary"),
        ("get", f"diary-entries/{entry['id']}"),
        ("delete", f"diary-photos/{entry['photos'][0]['id']}"),
    ):
        assert other.call(method, url, member=other.owner).status_code == 404, url
    r = other.call(
        "post",
        f"diary-entries/{entry['id']}/photos",
        {"photos": [{"attachment_id": other.file()}]},
        member=other.owner,
    )
    assert r.status_code == 404
    r = other.call(
        "patch",
        f"diary-entries/{entry['id']}",
        {"work_done": "x"},
        member=other.owner,
        IF_MATCH='"v1"',
    )
    assert r.status_code == 404
