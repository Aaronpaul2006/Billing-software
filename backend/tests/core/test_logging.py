"""Production logs: JSON lines carrying the request id (apps/core/logging.py)."""

import json
import logging

import pytest
from rest_framework.test import APIClient

from apps.core.logging import JsonFormatter, RequestIdFilter, request_id_var


def _format(record: logging.LogRecord) -> dict[str, object]:
    RequestIdFilter().filter(record)
    entry: dict[str, object] = json.loads(JsonFormatter().format(record))
    return entry


def _record(message: str, exc: BaseException | None = None) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc else None
    return logging.LogRecord("security", logging.WARNING, __file__, 1, message, (), exc_info)


def test_a_log_line_is_one_json_object() -> None:
    entry = _format(_record("login_failed user=u1"))
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "security"
    assert entry["message"] == "login_failed user=u1"
    assert str(entry["time"]).endswith("+00:00")
    assert "request_id" not in entry  # outside a request


def test_the_request_id_is_attached_while_a_request_runs() -> None:
    token = request_id_var.set("01a15b00-0000-7000-8000-000000000001")
    try:
        try:
            raise ValueError("boom")
        except ValueError as exc:
            entry = _format(_record("export failed", exc))
    finally:
        request_id_var.reset(token)
    assert entry["request_id"] == "01a15b00-0000-7000-8000-000000000001"
    assert "ValueError: boom" in str(entry["exception"])


@pytest.mark.django_db
def test_the_middleware_clears_the_request_id_after_the_request() -> None:
    response = APIClient().get("/healthz")
    assert response["X-Request-ID"]
    assert request_id_var.get() is None  # nothing leaks to the next request on this thread
