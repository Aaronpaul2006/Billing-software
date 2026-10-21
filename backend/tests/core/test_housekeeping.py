"""Housekeeping jobs (Celery beat): expired idempotency keys, uploads never completed.

They run without a tenant context through owner-only policies and SECURITY
DEFINER functions (db/schema.sql §8). The app role must gain nothing from them.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import boto3
import pytest
from django.db import ProgrammingError, connection, transaction
from django.test import override_settings
from django.utils import timezone
from moto import mock_aws

from apps.core.models import IdempotencyKey
from apps.core.tasks import purge_idempotency_keys
from apps.core.tenancy import tenant_context
from apps.files import storage
from apps.files.models import Attachment
from apps.files.tasks import purge_stale_uploads
from tests.factories import TenantFixture, make_tenant

pytestmark = pytest.mark.django_db


def _key(t: TenantFixture, *, expired: bool) -> uuid.UUID:
    with tenant_context(t.tenant_id, t.user_id):
        row = IdempotencyKey.objects.create(
            user_id=t.user_id,
            key=uuid.uuid4().hex,
            request_method="POST",
            request_path="/api/v1/payments",
            request_hash=b"h" * 32,
        )
        if expired:
            IdempotencyKey.objects.filter(pk=row.pk).update(
                expires_at=timezone.now() - timedelta(minutes=1)
            )
    key: uuid.UUID = row.pk
    return key


def _count(sql: str, t: TenantFixture | None = None) -> int:
    def run() -> int:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return int(cursor.fetchone()[0])

    if t is None:
        return run()
    with tenant_context(t.tenant_id, t.user_id):
        return run()


def test_expired_idempotency_keys_are_purged_in_every_tenant() -> None:
    a, b = make_tenant(), make_tenant()
    old_a, live_a = _key(a, expired=True), _key(a, expired=False)
    old_b, live_b = _key(b, expired=True), _key(b, expired=False)
    assert purge_idempotency_keys() == 2
    with tenant_context(a.tenant_id, a.user_id):
        assert set(IdempotencyKey.objects.values_list("pk", flat=True)) == {live_a}
    with tenant_context(b.tenant_id, b.user_id):
        assert set(IdempotencyKey.objects.values_list("pk", flat=True)) == {live_b}
    assert old_a != old_b
    assert purge_idempotency_keys() == 0


def test_the_app_role_sees_no_expired_keys_of_other_tenants() -> None:
    a, b = make_tenant(), make_tenant()
    _key(a, expired=True)
    assert _count("SELECT count(*) FROM idempotency_keys") == 0  # no context: nothing
    assert _count("SELECT count(*) FROM idempotency_keys", b) == 0  # B sees none of A's
    assert _count("SELECT count(*) FROM idempotency_keys", a) == 1


@pytest.fixture
def s3() -> Iterator[Any]:
    with (
        mock_aws(),
        override_settings(
            S3_ENDPOINT_URL=None,
            S3_PUBLIC_ENDPOINT_URL=None,
            S3_REGION="us-east-1",
            S3_BUCKET="test-bucket",
        ),
    ):
        storage._client.cache_clear()
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client
    storage._client.cache_clear()


def _upload(s3: Any, t: TenantFixture, *, status: str, age: timedelta) -> tuple[uuid.UUID, str]:
    key = f"tenants/{t.tenant_id}/uploads/{uuid.uuid7()}.pdf"
    s3.put_object(Bucket="test-bucket", Key=key, Body=b"%PDF-1.4", ContentType="application/pdf")
    with tenant_context(t.tenant_id, t.user_id):
        row = Attachment.objects.create(
            storage_key=key,
            original_filename="x.pdf",
            content_type="application/pdf",
            size_bytes=8,
            status=status,
            uploaded_by_id=t.user_id,
        )
        Attachment.objects.filter(pk=row.pk).update(created_at=timezone.now() - age)
    return row.pk, key


def test_uploads_left_pending_for_a_day_are_purged_with_their_objects(s3: Any) -> None:
    a, b = make_tenant(), make_tenant()
    stale_a = _upload(s3, a, status="PENDING", age=timedelta(days=2))
    stale_b = _upload(s3, b, status="PENDING", age=timedelta(hours=25))
    fresh = _upload(s3, a, status="PENDING", age=timedelta(hours=2))
    done = _upload(s3, b, status="AVAILABLE", age=timedelta(days=30))

    assert purge_stale_uploads() == 2
    for _, key in (stale_a, stale_b):
        assert storage.head(key) is None
    for _, key in (fresh, done):
        assert storage.head(key) is not None
    with tenant_context(a.tenant_id, a.user_id):
        assert set(Attachment.objects.values_list("pk", flat=True)) == {fresh[0]}
    with tenant_context(b.tenant_id, b.user_id):
        assert set(Attachment.objects.values_list("pk", flat=True)) == {done[0]}
    assert purge_stale_uploads() == 0


def test_a_storage_error_keeps_the_rows_for_the_next_run(
    s3: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = make_tenant()
    stale = _upload(s3, a, status="PENDING", age=timedelta(days=2))

    def broken(key: str) -> None:
        raise OSError("storage unreachable")

    monkeypatch.setattr(storage, "delete", broken)
    with pytest.raises(OSError, match="unreachable"):
        purge_stale_uploads()
    with tenant_context(a.tenant_id, a.user_id):
        assert Attachment.objects.filter(pk=stale[0]).exists()


def test_the_app_role_sees_no_stale_uploads_of_other_tenants(s3: Any) -> None:
    a, b = make_tenant(), make_tenant()
    _upload(s3, a, status="PENDING", age=timedelta(days=2))
    assert _count("SELECT count(*) FROM attachments") == 0
    assert _count("SELECT count(*) FROM attachments", b) == 0
    # Nor can it delete rows itself: only the purge function can.
    with pytest.raises(ProgrammingError, match="permission denied"), transaction.atomic():
        _count("WITH gone AS (DELETE FROM attachments RETURNING 1) SELECT count(*) FROM gone")
    assert _count("SELECT count(*) FROM attachments", a) == 1


def test_beat_runs_both_jobs_hourly(settings: Any) -> None:
    schedule = settings.CELERY_BEAT_SCHEDULE
    assert {entry["task"] for entry in schedule.values()} == {
        "apps.core.tasks.purge_idempotency_keys",
        "apps.files.tasks.purge_stale_uploads",
        "apps.exports.tasks.purge_old_exports",
    }
    assert all(entry["schedule"] == 3600.0 for entry in schedule.values())
