"""Parallel issuing through the real service: unique, gapless numbers."""

import threading
import uuid
from typing import Any

import pytest
from django.db import connections

from apps.core.tenancy import Principal, tenant_context
from apps.documents.services import lifecycle

from .test_drafts import World
from .test_lifecycle import next_number, series


@pytest.mark.usefixtures("committed_db")
def test_parallel_issues_get_unique_gapless_numbers() -> None:
    w = World()
    s = series(w)
    docs = [w.create().json()["id"] for _ in range(4)]
    principal = Principal(
        user_id=w.t.user_id, tenant_id=w.t.tenant_id, role="OWNER", amr=frozenset({"pwd", "otp"})
    )
    barrier = threading.Barrier(len(docs))
    numbers: list[Any] = []

    def run(doc_id: str) -> None:
        try:
            barrier.wait(timeout=10)
            with tenant_context(w.t.tenant_id, w.t.user_id):
                numbers.append(lifecycle.issue(principal, uuid.UUID(doc_id), 1).doc_number)
        except Exception as exc:  # collected and asserted below
            numbers.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(d,)) for d in docs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(numbers) == ["INV/0001", "INV/0002", "INV/0003", "INV/0004"], numbers
    assert next_number(s, w) == 5
