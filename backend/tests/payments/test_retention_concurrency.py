"""Parallel retention releases through the real service (committed data,
so no module-wide django_db transaction here)."""

import threading
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections

from apps.core.errors import Invalid
from apps.core.tenancy import Principal, tenant_context
from apps.payments import retention

from .test_retention import Held


@pytest.mark.usefixtures("committed_db")
def test_parallel_releases_cannot_over_release() -> None:
    """28900 held; two releases of 20000 at the same moment: one wins."""
    h = Held()
    principal = Principal(
        user_id=h.t.user_id, tenant_id=h.t.tenant_id, role="OWNER", amr=frozenset({"pwd", "otp"})
    )
    barrier = threading.Barrier(2)
    outcomes: list[Any] = []

    def run() -> None:
        try:
            barrier.wait(timeout=10)
            with tenant_context(h.t.tenant_id, h.t.user_id):
                row = retention.release(
                    principal,
                    {
                        "project_id": h.project.pk,
                        "release_date": date(2026, 11, 5),
                        "amount": Decimal("20000.00"),
                    },
                )
                outcomes.append(str(row.amount))
        except Invalid as exc:
            outcomes.append(exc.code)
        except Exception as exc:  # collected and asserted below
            outcomes.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(map(str, outcomes)) == ["20000.00", "exceeds_retention_held"], outcomes
