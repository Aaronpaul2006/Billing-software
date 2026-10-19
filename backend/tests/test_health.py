import pytest
from django.test import Client, override_settings


def test_healthz_needs_no_database(client: Client) -> None:
    # No django_db mark: any database access in this test would fail it.
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_rejects_post(client: Client) -> None:
    assert client.post("/healthz").status_code == 405


@pytest.mark.django_db
def test_readyz_ok_when_database_and_redis_are_up(client: Client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.django_db
@override_settings(REDIS_URL="redis://127.0.0.1:1/0")  # nothing listens on port 1
def test_readyz_503_when_redis_is_down(client: Client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "fail"}
