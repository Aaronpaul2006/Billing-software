"""Speed check (W.7): every page's endpoint against a large company.

Opt-in, because seeding takes a while:  PERF=1 uv run pytest tests/perf -s
(PERF_EXPLAIN=1 also prints the plan of each slow page's slowest query.)

The company: 500 clients, 60 projects with 3,000 BOQ items, about 11,000 bills
and quotations over two financial years (4 lines each, 4 % left as drafts),
8,000 payments allocated to bills, 4,000 expenses. Seeded with set-based SQL
as the app role (RLS and every trigger apply, as in production).

Each endpoint is called once to warm up, then timed three times (median),
and its SQL queries are counted. Budgets: 500 ms and 25 queries per request
(a page list must not grow its query count with the number of rows).
"""

import os
import statistics
import time
from collections.abc import Callable
from functools import partial
from typing import Any

import pytest
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.core.tenancy import tenant_context
from apps.parties.models import Party
from tests.factories import Member, TenantFixture, add_client, make_tenant, owner_member

pytestmark = [
    # Committed, so the owner can ANALYZE it (as autovacuum would in production);
    # the test database is dropped after the session.
    pytest.mark.usefixtures("committed_db"),
    pytest.mark.skipif(os.environ.get("PERF") != "1", reason="speed check: set PERF=1"),
]

BUDGET_MS = 500
BUDGET_QUERIES = 25
PARTIES, PROJECTS, BOQ_PER_PROJECT, DOCUMENTS, PAYMENTS, EXPENSES = (
    500,
    60,
    50,
    11_000,
    8_000,
    4_000,
)

SEED = [
    # clients
    """INSERT INTO parties (tenant_id, display_name, gst_treatment, state_code, email, created_by)
       SELECT %(t)s, 'Client ' || lpad(i::text, 4, '0'), 'UNREGISTERED', '32',
              'client' || i || '@example.com', %(u)s
         FROM generate_series(1, %(parties)s) i""",
    # projects: client k * 8 has project k
    """INSERT INTO projects (tenant_id, code, name, client_party_id, gst_registration_id,
                             site_state_code, contract_value, created_by)
       SELECT %(t)s, 'P' || lpad(k::text, 3, '0'), 'Site ' || k,
              (SELECT id FROM parties WHERE display_name = 'Client ' || lpad((k * 8)::text, 4, '0')),
              %(reg)s, '32', 5000000, %(u)s
         FROM generate_series(1, %(projects)s) k""",
    """INSERT INTO boq_items (tenant_id, project_id, item_code, description, unit, contract_qty,
                              rate, sort_order)
       SELECT %(t)s, p.id, j::text, 'Item ' || j, 'cum', 100, 1000, j
         FROM projects p CROSS JOIN generate_series(1, %(boq)s) j""",
    """INSERT INTO document_series (tenant_id, gst_registration_id, doc_type, fy_start_year, prefix)
       SELECT %(t)s, %(reg)s, d.t, y, d.p || y || '/'
         FROM (VALUES ('TAX_INVOICE', 'I'), ('QUOTATION', 'Q')) d(t, p)
        CROSS JOIN (VALUES (2025), (2026)) fy(y)""",
    # drafts first (the trigger allows nothing else), spread over Apr 2025 - Nov 2026
    """WITH pa AS (SELECT array_agg(id ORDER BY display_name) a FROM parties),
            pr AS (SELECT array_agg(id ORDER BY code) a FROM projects)
       INSERT INTO documents (tenant_id, doc_type, gst_registration_id, doc_date, valid_until,
                              party_id, project_id, place_of_supply, supply_type, created_by)
       SELECT %(t)s, CASE WHEN i %% 11 = 0 THEN 'QUOTATION' ELSE 'TAX_INVOICE' END, %(reg)s,
              date '2025-04-01' + (i %% 580),
              CASE WHEN i %% 11 = 0 THEN date '2025-04-01' + (i %% 580) + 30 END,
              pa.a[1 + i %% %(parties)s],
              CASE WHEN (1 + i %% %(parties)s) %% 8 = 0 AND (1 + i %% %(parties)s) / 8 <= %(projects)s
                   THEN pr.a[(1 + i %% %(parties)s) / 8] END,
              '32', 'INTRA_STATE', %(u)s
         FROM generate_series(1, %(documents)s) i, pa, pr""",
    """INSERT INTO document_lines (tenant_id, document_id, line_no, description, sac_hsn,
                                   quantity, rate, taxable_value, gst_rate, cgst_amount,
                                   sgst_amount, line_total)
       SELECT %(t)s, d.id, n, 'RCC work ' || n, '9954', 10, 1000, 10000, 18, 900, 900, 11800
         FROM documents d CROSS JOIN generate_series(1, 4) n""",
    """UPDATE documents SET subtotal = 40000, cgst_amount = 3600, sgst_amount = 3600,
                            grand_total = 47200, net_receivable = 47200""",
    # issue 96 %: numbered per series (type and financial year)
    """WITH n AS (
         SELECT d.id, s.id AS series_id, s.prefix,
                row_number() OVER (PARTITION BY s.id ORDER BY d.doc_date, d.id) AS rn
           FROM documents d
           JOIN document_series s ON s.doc_type = d.doc_type AND s.fy_start_year = d.fy_start_year
          WHERE (abs(hashtext(d.id::text)) %% 25) <> 0)
       UPDATE documents d
          SET status = 'ISSUED', series_id = n.series_id, doc_number = n.prefix || n.rn,
              issued_at = now(), issued_by = %(u)s, supplier_snapshot = '{}',
              party_snapshot = '{}'
         FROM n WHERE d.id = n.id""",
    # payments for the oldest invoices (a third paid in full), then their allocations
    """INSERT INTO payments (tenant_id, party_id, payment_date, amount, mode, notes, created_by)
       SELECT %(t)s, d.party_id, least(d.doc_date + 20, current_date),
              CASE WHEN rn %% 3 = 0 THEN 47200 ELSE 20000 END, 'UPI', d.id::text, %(u)s
         FROM (SELECT id, party_id, doc_date, row_number() OVER (ORDER BY doc_date, id) rn
                 FROM documents WHERE status = 'ISSUED' AND doc_type = 'TAX_INVOICE') d
        WHERE rn <= %(payments)s""",
    """INSERT INTO allocations (tenant_id, document_id, payment_id, amount, created_by)
       SELECT %(t)s, p.notes::uuid, p.id, p.amount, %(u)s FROM payments p""",
    """WITH pr AS (SELECT array_agg(id ORDER BY code) a FROM projects)
       INSERT INTO expenses (tenant_id, project_id, category, expense_date, description,
                             taxable_value, gst_amount, total_amount, itc_eligible, created_by)
       SELECT %(t)s, pr.a[1 + i %% %(projects)s], 'MATERIAL', date '2025-04-01' + (i %% 580),
              'Cement ' || i, 5000, 900, 5900, i %% 2 = 0, %(u)s
         FROM generate_series(1, %(expenses)s) i, pr""",
]


def _first(cursor: Any) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


class Company:
    def __init__(self) -> None:
        self.t: TenantFixture = make_tenant("Big Builders")
        params: dict[str, Any] = {
            "t": self.t.tenant_id,
            "u": self.t.user_id,
            "reg": self.t.registration_id,
            "parties": PARTIES,
            "projects": PROJECTS,
            "boq": BOQ_PER_PROJECT,
            "documents": DOCUMENTS,
            "payments": PAYMENTS,
            "expenses": EXPENSES,
        }
        started = time.perf_counter()
        with tenant_context(self.t.tenant_id, self.t.user_id), connection.cursor() as cursor:
            for statement in SEED:
                cursor.execute(statement, params)
            cursor.execute("SELECT count(*) FROM documents WHERE status = 'ISSUED'")
            issued = _first(cursor)
            party = Party.objects.order_by("display_name").first()
            assert party is not None
            self.party: Party = party
            cursor.execute(
                "SELECT id FROM documents WHERE party_id = %s AND status = 'ISSUED' LIMIT 1",
                [self.party.pk],
            )
            self.document = _first(cursor)
            cursor.execute("SELECT id FROM projects ORDER BY code LIMIT 1")
            self.project = _first(cursor)
            cursor.execute("SELECT id FROM payments ORDER BY id DESC LIMIT 1")
            self.payment = _first(cursor)
        # Statistics, as autovacuum keeps them in production. Only the owner may
        # ANALYZE: as the app role it is silently skipped and every estimate is 1 row.
        with connections["owner"].cursor() as cursor:
            cursor.execute("ANALYZE")
        print(f"\nseeded {issued} issued documents in {time.perf_counter() - started:.1f} s")
        self.owner: Member = owner_member(self.t)
        self.client: Member = add_client(self.t, self.party)


def _explain_slowest(c: Company, queries: CaptureQueriesContext) -> None:
    """PERF_EXPLAIN=1: the plan of a slow page's slowest query, to see why."""
    slowest = max(queries.captured_queries, key=lambda q: float(q["time"]))
    with tenant_context(c.t.tenant_id, c.t.user_id), connection.cursor() as cursor:
        cursor.execute("EXPLAIN (ANALYZE, BUFFERS) " + slowest["sql"])
        print(f"\n--- {slowest['time']} s\n{slowest['sql'][:400]}")
        print("\n".join(row[0] for row in cursor.fetchall()))


def _measure(call: Callable[[], Any]) -> tuple[float, int, int, CaptureQueriesContext]:
    first = call()
    status = first.status_code
    times = []
    for _ in range(3):
        started = time.perf_counter()
        call()
        times.append((time.perf_counter() - started) * 1000)
    with CaptureQueriesContext(connection) as queries:
        call()
    return statistics.median(times), len(queries), status, queries


def test_every_page_is_fast_with_a_large_company() -> None:
    c = Company()
    api = APIClient()
    staff = {"HTTP_AUTHORIZATION": f"Bearer {c.owner.access_token}"}
    client = {"HTTP_AUTHORIZATION": f"Bearer {c.client.access_token}"}
    fy = {"from": "2026-04-01", "to": "2026-11-02"}
    pages: dict[str, tuple[str, dict[str, str], dict[str, Any]]] = {
        "dashboard": ("/api/v1/reports/dashboard", fy, staff),
        "summary": ("/api/v1/reports/summary", fy, staff),
        "receivables": ("/api/v1/reports/receivables", {}, staff),
        "billing by month": ("/api/v1/reports/billing-by-month", fy, staff),
        "projects report": ("/api/v1/reports/projects", {}, staff),
        "gst summary": ("/api/v1/reports/gst-summary", {"period": "2026-10"}, staff),
        "documents": ("/api/v1/documents", {}, staff),
        "documents, search": ("/api/v1/documents", {"q": "I2026/12"}, staff),
        "documents, unpaid": ("/api/v1/documents", {"payment_state": "OPEN"}, staff),
        "documents, one client": ("/api/v1/documents", {"party_id": str(c.party.pk)}, staff),
        "document": (f"/api/v1/documents/{c.document}", {}, staff),
        "payments": ("/api/v1/payments", {}, staff),
        "payment": (f"/api/v1/payments/{c.payment}", {}, staff),
        "parties": ("/api/v1/parties", {}, staff),
        "parties, search": ("/api/v1/parties", {"q": "Client 04"}, staff),
        "statement": (f"/api/v1/parties/{c.party.pk}/statement", {}, staff),
        "projects": ("/api/v1/projects", {}, staff),
        "boq": (f"/api/v1/projects/{c.project}/boq-items", {}, staff),
        "boq progress": (f"/api/v1/projects/{c.project}/boq-progress", {}, staff),
        "expenses": ("/api/v1/expenses", {}, staff),
        "portal documents": ("/api/v1/portal/documents", {}, client),
        "portal payments": ("/api/v1/portal/payments", {}, client),
        "portal statement": ("/api/v1/portal/statement", {}, client),
    }
    rows, slow = [], []
    for name, (path, query, headers) in pages.items():
        ms, n, status, queries = _measure(partial(api.get, path, query, **headers))
        rows.append(f"{name:<24} {status:>4} {ms:>8.1f} ms {n:>4} queries")
        if status != 200 or ms > BUDGET_MS or n > BUDGET_QUERIES:
            slow.append(name)
            if ms > BUDGET_MS and os.environ.get("PERF_EXPLAIN") == "1":
                _explain_slowest(c, queries)
    print("\n" + "\n".join(rows))
    assert not slow, f"over budget ({BUDGET_MS} ms, {BUDGET_QUERIES} queries): {slow}"
