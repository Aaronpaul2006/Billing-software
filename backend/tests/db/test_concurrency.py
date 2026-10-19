"""Concurrency guarantees, with real commits and two simultaneous connections.

PGlite (db/tests) has a single connection, so these could not be checked
before. Each worker holds its transaction open with pg_sleep() after the
critical statement, so the two transactions genuinely overlap and the second
has to wait for the first one's locks.
"""

import threading
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connections

from apps.core.tenancy import tenant_context

from .seed import Seeded, add_line, issued_invoice, new_draft, seed_tenant, set_totals, sql

pytestmark = pytest.mark.usefixtures("committed_db")

HOLD = 0.3  # seconds each transaction keeps its locks before committing


def run_concurrently(*workers: Callable[[], Any]) -> list[Any]:
    """Start the workers at the same moment; return each result or exception."""
    barrier = threading.Barrier(len(workers))
    results: list[Any] = [None] * len(workers)

    def run(i: int, work: Callable[[], Any]) -> None:
        try:
            barrier.wait(timeout=10)
            results[i] = work()
        except Exception as exc:  # collected and asserted by the test
            results[i] = exc
        finally:
            connections.close_all()  # each thread has its own connections

    threads = [threading.Thread(target=run, args=(i, w)) for i, w in enumerate(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _errors(results: list[Any]) -> list[str]:
    return [str(r) for r in results if isinstance(r, DatabaseError)]


@pytest.fixture
def a() -> Seeded:
    return seed_tenant("A", "32ABCDE1234F1Z5", "32")


def _ready_draft(a: Seeded) -> uuid.UUID:
    """A draft with a line and correct totals (issuable)."""
    with tenant_context(a.tenant, a.user):
        doc = new_draft(a, uuid.uuid7())
        add_line(a, doc)
        set_totals(doc)
    return doc


# --- gapless numbering (docs/01-architecture.md §5.3) --------------------------------


def issue_with_series_lock(a: Seeded, doc: uuid.UUID) -> str:
    """The documented issue algorithm: lock the counter row, take, increment."""
    with tenant_context(a.tenant, a.user):
        [(next_number, prefix, pad)] = sql(
            "SELECT next_number, prefix, pad_width FROM document_series WHERE id = %s FOR UPDATE",
            [a.series],
        )
        sql("SELECT pg_sleep(%s)", [HOLD])
        number = f"{prefix}{next_number:0{pad}d}"
        sql(
            "UPDATE document_series SET next_number = next_number + 1, updated_at = now()"
            " WHERE id = %s",
            [a.series],
        )
        sql(
            "UPDATE documents SET status = 'ISSUED', series_id = %s, doc_number = %s,"
            " issued_at = now(), issued_by = %s, supplier_snapshot = '{}', party_snapshot = '{}'"
            " WHERE id = %s",
            [a.series, number, a.user, doc],
        )
        return number


def test_parallel_issue_gets_unique_gapless_numbers(a: Seeded) -> None:
    first, second = _ready_draft(a), _ready_draft(a)
    results = run_concurrently(
        lambda: issue_with_series_lock(a, first), lambda: issue_with_series_lock(a, second)
    )
    assert sorted(results) == ["INV/0001", "INV/0002"], results
    with tenant_context(a.tenant, a.user):
        assert sql("SELECT next_number FROM document_series WHERE id = %s", [a.series]) == [(3,)]


def test_without_the_lock_the_unique_index_still_prevents_duplicates(a: Seeded) -> None:
    """The anti-pattern (read the counter, then write) must not create duplicates."""
    first, second = _ready_draft(a), _ready_draft(a)

    def naive_issue(doc: uuid.UUID) -> str:
        with tenant_context(a.tenant, a.user):
            [(next_number,)] = sql(
                "SELECT next_number FROM document_series WHERE id = %s", [a.series]
            )
            sql("SELECT pg_sleep(%s)", [HOLD])
            number = f"INV/{next_number:04d}"
            sql(
                "UPDATE documents SET status = 'ISSUED', series_id = %s, doc_number = %s,"
                " issued_at = now(), issued_by = %s, supplier_snapshot = '{}',"
                " party_snapshot = '{}' WHERE id = %s",
                [a.series, number, a.user, doc],
            )
            return number

    results = run_concurrently(lambda: naive_issue(first), lambda: naive_issue(second))
    assert [r for r in results if isinstance(r, str)] == ["INV/0001"], results
    [error] = _errors(results)
    assert "documents_number_uq" in error


def test_failed_issue_leaves_no_gap(a: Seeded) -> None:
    """A rolled-back issue rolls back the counter too: no number is lost."""
    empty = uuid.uuid7()
    with tenant_context(a.tenant, a.user):
        new_draft(a, empty)  # no lines: the issue trigger rejects it
    with pytest.raises(DatabaseError, match="no lines"):
        issue_with_series_lock(a, empty)
    assert issue_with_series_lock(a, _ready_draft(a)) == "INV/0001"


# --- settlement cannot exceed what is owed or what was paid --------------------------


def _payment(a: Seeded, amount: int) -> uuid.UUID:
    payment = uuid.uuid7()
    with tenant_context(a.tenant, a.user):
        sql(
            "INSERT INTO payments (id, tenant_id, party_id, payment_date, amount, mode, created_by)"
            " VALUES (%s, %s, %s, '2026-10-20', %s, 'BANK_TRANSFER', %s)",
            [payment, a.tenant, a.party, amount, a.user],
        )
    return payment


def allocate(a: Seeded, doc: uuid.UUID, payment: uuid.UUID, amount: int) -> str:
    with tenant_context(a.tenant, a.user):
        sql(
            "INSERT INTO allocations (tenant_id, document_id, payment_id, amount, created_by)"
            " VALUES (%s, %s, %s, %s, %s)",
            [a.tenant, doc, payment, amount, a.user],
        )
        sql("SELECT pg_sleep(%s)", [HOLD])
        return "allocated"


def test_parallel_allocations_cannot_overpay_an_invoice(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        invoice = issued_invoice(a)  # net receivable 11100
    p1, p2 = _payment(a, 8000), _payment(a, 8000)

    results = run_concurrently(
        lambda: allocate(a, invoice, p1, 7000), lambda: allocate(a, invoice, p2, 7000)
    )
    assert results.count("allocated") == 1, results
    [error] = _errors(results)
    assert "documents_amount_settled_check" in error or "check constraint" in error
    with tenant_context(a.tenant, a.user):
        assert sql("SELECT amount_settled FROM documents WHERE id = %s", [invoice]) == [
            (Decimal("7000.00"),)
        ]


def test_parallel_allocations_cannot_spend_a_payment_twice(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        first = issued_invoice(a)
        second = new_draft(a, uuid.uuid7())
        add_line(a, second)
        set_totals(second)
        sql(
            "UPDATE documents SET status = 'ISSUED', series_id = %s, doc_number = 'INV/0002',"
            " issued_at = now(), issued_by = %s, supplier_snapshot = '{}', party_snapshot = '{}'"
            " WHERE id = %s",
            [a.series, a.user, second],
        )
    payment = _payment(a, 8000)

    results = run_concurrently(
        lambda: allocate(a, first, payment, 6000), lambda: allocate(a, second, payment, 6000)
    )
    assert results.count("allocated") == 1, results
    [error] = _errors(results)
    assert "exceeds the unallocated amount" in error
    with tenant_context(a.tenant, a.user):
        assert sql(
            "SELECT coalesce(sum(amount), 0) FROM allocations WHERE payment_id = %s", [payment]
        ) == [(Decimal("6000.00"),)]
