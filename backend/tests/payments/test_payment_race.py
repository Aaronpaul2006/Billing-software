"""Two payments race to settle the same invoice through the real service.

The database decides (row lock + CHECK); the loser gets the same API error
code the pre-checks would have given.
"""

import threading
import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections

from apps.core.errors import Invalid
from apps.core.tenancy import Principal, tenant_context
from apps.payments import services

from .test_payments import Money


@pytest.mark.usefixtures("committed_db")
def test_parallel_allocations_one_wins_the_loser_gets_a_clean_error() -> None:
    m = Money()
    inv = m.invoice()  # net receivable 323680.00
    principal = Principal(
        user_id=m.t.user_id, tenant_id=m.t.tenant_id, role="OWNER", amr=frozenset({"pwd", "otp"})
    )
    payments = [m.pay("300000.00").json()["id"] for _ in range(2)]
    barrier = threading.Barrier(2)
    results: list[Any] = []

    def allocate(payment_id: str) -> None:
        try:
            barrier.wait(timeout=10)
            with tenant_context(m.t.tenant_id, m.t.user_id):
                services.allocate(
                    principal,
                    uuid.UUID(payment_id),
                    [{"document_id": uuid.UUID(inv["id"]), "amount": Decimal("300000.00")}],
                )
            results.append("ok")
        except Exception as exc:  # collected and asserted below
            results.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=allocate, args=(p,)) for p in payments]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results.count("ok") == 1, results
    [loser] = [r for r in results if r != "ok"]
    assert isinstance(loser, Invalid), loser
    assert loser.code == "allocation_exceeds_outstanding"
    assert m.totals(inv["id"])["amount_settled"] == "300000.00"
