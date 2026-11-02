"""The main dashboard (W.6): everything the owner looks at first, in one
request. Parameterised SQL over RLS-protected tables and security_invoker
views, every query also filtered by tenant (like apps.reports.queries).

Margin = billed taxable value - cost (expenses; their GST counts as cost
unless input tax credit can be claimed), the same rule as the project report.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from . import queries
from .queries import BOOK_SQL, _one, _rows

MONTHS = 12
OVERDUE_ROWS = 10
LOSING_ROWS = 5
DRAFT_ROWS = 5


def _month_start(d: date, back: int = 0) -> date:
    index = d.year * 12 + d.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def totals(tenant: uuid.UUID, start: date, end: date, book: str) -> dict[str, Decimal]:
    base = queries.totals(tenant, start, end, book)
    cost = _one(
        """SELECT coalesce(sum(e.taxable_value
                               + CASE WHEN e.itc_eligible THEN 0 ELSE e.gst_amount END), 0)
                  AS cost
             FROM expenses e
            WHERE e.tenant_id = %s AND e.status = 'RECORDED'
              AND e.expense_date BETWEEN %s AND %s""",
        [tenant, start, end],
    )["cost"]
    overdue = _one(
        f"""SELECT coalesce(sum(d.outstanding), 0) AS overdue
              FROM v_receivables d
             WHERE d.tenant_id = %s AND d.ageing_bucket <> 'NOT_DUE' AND {BOOK_SQL[book]}""",  # noqa: S608
        [tenant],
    )["overdue"]
    return {
        "billed": base["billed"],
        "collected": base["collected"],
        "outstanding": base["outstanding"],
        "overdue": overdue,
        "expenses": base["expenses"],
        "margin": base["taxable"] - cost,
    }


def months(tenant: uuid.UUID, end: date, book: str) -> list[dict[str, Any]]:
    """Billed and collected per month, the 12 months up to `end`'s month (empty ones too)."""
    first = _month_start(end, MONTHS - 1)
    b = BOOK_SQL[book]
    if book == "ALL":
        collected_sql = """SELECT date_trunc('month', p.payment_date)::date AS month,
                                  sum(p.amount) AS collected
                             FROM payments p
                            WHERE p.tenant_id = %(t)s AND p.status = 'RECORDED'
                              AND p.payment_date BETWEEN %(first)s AND %(end)s
                            GROUP BY 1"""
    else:
        collected_sql = f"""SELECT date_trunc('month', p.payment_date)::date AS month,
                                   sum(a.amount) AS collected
                              FROM allocations a
                              JOIN payments p ON p.tenant_id = a.tenant_id AND p.id = a.payment_id
                              LEFT JOIN documents dd
                                ON dd.tenant_id = a.tenant_id AND dd.id = a.document_id
                              LEFT JOIN retention_releases r
                                ON r.tenant_id = a.tenant_id AND r.id = a.retention_release_id
                              CROSS JOIN LATERAL (
                                SELECT coalesce(dd.is_gst_document, r.book = 'GST')
                                       AS is_gst_document
                              ) d
                             WHERE a.tenant_id = %(t)s AND p.status = 'RECORDED'
                               AND p.payment_date BETWEEN %(first)s AND %(end)s AND {b}
                             GROUP BY 1"""  # noqa: S608
    book_filter = "" if book == "ALL" else "AND v.book = %(book)s"
    return _rows(
        f"""WITH m AS (
                SELECT generate_series(%(first)s::date, %(last)s::date, interval '1 month')::date
                       AS month
            ),
            billed AS (
                SELECT v.month, sum(v.billed) AS billed
                  FROM v_billing_summary v
                 WHERE v.tenant_id = %(t)s AND v.month BETWEEN %(first)s AND %(end)s {book_filter}
                 GROUP BY v.month
            ),
            collected AS ({collected_sql})
            SELECT m.month, coalesce(b.billed, 0) AS billed, coalesce(c.collected, 0) AS collected
              FROM m
              LEFT JOIN billed b ON b.month = m.month
              LEFT JOIN collected c ON c.month = m.month
             ORDER BY m.month""",  # noqa: S608 - fixed fragments
        {"t": tenant, "first": first, "last": _month_start(end), "end": end, "book": book},
    )


def overdue(tenant: uuid.UUID, book: str) -> dict[str, Any]:
    """Past-due bills (not retention releases: those have no reminders), oldest first."""
    where = f"""d.tenant_id = %s AND d.document_id IS NOT NULL
                AND d.ageing_bucket <> 'NOT_DUE' AND {BOOK_SQL[book]}"""
    count = _one(
        f"SELECT count(*)::int AS n FROM v_receivables d WHERE {where}",  # noqa: S608
        [tenant],
    )["n"]
    rows = _rows(
        f"""SELECT d.document_id, d.doc_type, d.doc_number, d.party_id,
                   p.display_name AS party_name, coalesce(d.due_date, d.doc_date) AS due_date,
                   (current_date - coalesce(d.due_date, d.doc_date))::int AS days_overdue,
                   d.outstanding, p.email IS NOT NULL AS party_has_email,
                   (SELECT max(r.sent_at) FROM payment_reminders r
                     WHERE r.tenant_id = d.tenant_id AND r.document_id = d.document_id)
                     AS last_reminder_at
              FROM v_receivables d
              JOIN parties p ON p.tenant_id = d.tenant_id AND p.id = d.party_id
             WHERE {where}
             ORDER BY coalesce(d.due_date, d.doc_date), d.doc_number
             LIMIT %s""",  # noqa: S608
        [tenant, OVERDUE_ROWS],
    )
    return {"count": count, "results": rows}


def losing_projects(tenant: uuid.UUID) -> list[dict[str, Any]]:
    """Projects whose costs so far exceed what was billed, worst first."""
    rows = [r for r in queries.projects(tenant) if r["margin"] < 0]
    return sorted(rows, key=lambda r: (r["margin"], r["code"]))[:LOSING_ROWS]


def drafts(tenant: uuid.UUID) -> dict[str, Any]:
    """Drafts not yet issued, the longest waiting first."""
    count = _one(
        "SELECT count(*)::int AS n FROM documents WHERE tenant_id = %s AND status = 'DRAFT'",
        [tenant],
    )["n"]
    rows = _rows(
        """SELECT d.id, d.doc_type, d.doc_date, p.display_name AS party_name,
                  d.grand_total, d.updated_at
             FROM documents d
             JOIN parties p ON p.tenant_id = d.tenant_id AND p.id = d.party_id
            WHERE d.tenant_id = %s AND d.status = 'DRAFT'
            ORDER BY d.updated_at, d.id
            LIMIT %s""",
        [tenant, DRAFT_ROWS],
    )
    return {"count": count, "results": rows}


def dashboard(
    tenant: uuid.UUID, start: date, end: date, book: str, previous: tuple[date, date]
) -> dict[str, Any]:
    """`previous`: the period before, for comparison (apps.reports.serializers.previous_period)."""
    return {
        "book": book,
        "period": {"from": start, "to": end},
        "previous_period": {"from": previous[0], "to": previous[1]},
        "totals": totals(tenant, start, end, book),
        "previous": totals(tenant, previous[0], previous[1], book),
        "months": months(tenant, end, book),
        "overdue": overdue(tenant, book),
        "losing_projects": losing_projects(tenant),
        "drafts": drafts(tenant),
    }
