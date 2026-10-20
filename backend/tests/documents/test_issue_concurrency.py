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


@pytest.mark.usefixtures("committed_db")
def test_parallel_bills_cannot_together_pass_the_boq_quantity() -> None:
    """Two drafts each fit the BOQ alone (40 + 40 of 60); issued at the same
    moment, the row lock on the BOQ item lets exactly one through."""
    from decimal import Decimal

    from apps.core.errors import Invalid
    from apps.projects.models import BoqItem

    w = World()
    series(w)
    with tenant_context(w.t.tenant_id, w.t.user_id):
        item = BoqItem.objects.create(
            project=w.project,
            item_code="2.1",
            description="RCC",
            unit="cum",
            contract_qty=Decimal("60"),
            rate=Decimal("6800"),
        )
    line = [{"boq_item_id": str(item.pk), "quantity": "40"}]
    docs = [w.create(lines=line, is_ra_bill=True).json()["id"], w.create(lines=line).json()["id"]]
    principal = Principal(
        user_id=w.t.user_id, tenant_id=w.t.tenant_id, role="OWNER", amr=frozenset({"pwd", "otp"})
    )
    barrier = threading.Barrier(len(docs))
    outcomes: list[Any] = []

    def run(doc_id: str) -> None:
        try:
            barrier.wait(timeout=10)
            with tenant_context(w.t.tenant_id, w.t.user_id):
                outcomes.append(lifecycle.issue(principal, uuid.UUID(doc_id), 1).doc_number)
        except Invalid as exc:
            outcomes.append(exc.code)
        except Exception as exc:  # collected and asserted below
            outcomes.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(d,)) for d in docs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(map(str, outcomes)) == ["INV/0001", "exceeds_boq_quantity"], outcomes
