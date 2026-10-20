"""Report queries: parameterised SQL over the security_invoker views and
tables, so Row-Level Security applies; every query also filters tenant_id
explicitly (defence in depth). Amounts come back as Decimal.

Signs: credit notes count negative; only ISSUED documents count (cancelled
ones count nowhere; accepted / declined are quotations, not revenue).
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import connection

SIGNED = "CASE WHEN d.doc_type = 'CREDIT_NOTE' THEN -1 ELSE 1 END"
BOOK_SQL = {
    "ALL": "TRUE",
    "GST": "d.is_gst_document",
    "NON_GST": "NOT d.is_gst_document",
}


def _rows(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [c.name for c in cursor.description or []]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _one(sql: str, params: list[Any]) -> dict[str, Any]:
    return _rows(sql, params)[0]


def totals(tenant: uuid.UUID, start: date, end: date, book: str) -> dict[str, Decimal]:
    """Billed, tax, collected and expenses in [start, end]; outstanding now."""
    b = BOOK_SQL[book]
    billed = _one(
        f"""SELECT coalesce(sum({SIGNED} * d.grand_total), 0) AS billed,
                   coalesce(sum({SIGNED} * (d.cgst_amount + d.sgst_amount + d.igst_amount
                                            + d.cess_amount)), 0) AS tax,
                   coalesce(sum({SIGNED} * d.subtotal), 0) AS taxable
              FROM documents d
             WHERE d.tenant_id = %s AND d.status = 'ISSUED' AND d.is_revenue
               AND d.doc_date BETWEEN %s AND %s AND {b}""",  # noqa: S608 - fixed fragments
        [tenant, start, end],
    )
    if book == "ALL":  # all money received, including advances not yet allocated
        collected = _one(
            """SELECT coalesce(sum(p.amount), 0) AS collected FROM payments p
                WHERE p.tenant_id = %s AND p.status = 'RECORDED'
                  AND p.payment_date BETWEEN %s AND %s""",
            [tenant, start, end],
        )
    else:  # what reached this book's documents and retention releases
        collected = _one(
            f"""SELECT coalesce(sum(a.amount), 0) AS collected
                  FROM allocations a
                  JOIN payments p ON p.tenant_id = a.tenant_id AND p.id = a.payment_id
                  LEFT JOIN documents dd
                    ON dd.tenant_id = a.tenant_id AND dd.id = a.document_id
                  LEFT JOIN retention_releases r
                    ON r.tenant_id = a.tenant_id AND r.id = a.retention_release_id
                  CROSS JOIN LATERAL (
                    SELECT coalesce(dd.is_gst_document, r.book = 'GST') AS is_gst_document
                  ) d
                 WHERE a.tenant_id = %s AND p.status = 'RECORDED'
                   AND p.payment_date BETWEEN %s AND %s AND {b}""",  # noqa: S608
            [tenant, start, end],
        )
    expenses = _one(
        """SELECT coalesce(sum(e.total_amount), 0) AS expenses FROM expenses e
            WHERE e.tenant_id = %s AND e.status = 'RECORDED'
              AND e.expense_date BETWEEN %s AND %s""",
        [tenant, start, end],
    )
    outstanding = _one(
        f"""SELECT coalesce(sum(d.outstanding), 0) AS outstanding
              FROM v_receivables d WHERE d.tenant_id = %s AND {b}""",  # noqa: S608
        [tenant],
    )
    return {**billed, **collected, **expenses, **outstanding}


def billing_by_month(tenant: uuid.UUID, start: date, end: date, book: str) -> list[dict[str, Any]]:
    where = "" if book == "ALL" else "AND v.book = %s"
    params: list[Any] = [tenant, start.replace(day=1), end]
    if book != "ALL":
        params.append(book)
    return _rows(
        f"""SELECT v.month, v.book, sum(v.document_count)::int AS document_count,
                   sum(v.taxable_value) AS taxable_value, sum(v.tax) AS tax,
                   sum(v.billed) AS billed
              FROM v_billing_summary v
             WHERE v.tenant_id = %s AND v.month BETWEEN %s AND %s {where}
             GROUP BY v.month, v.book ORDER BY v.month, v.book""",  # noqa: S608
        params,
    )


BUCKETS = ("NOT_DUE", "1_30", "31_60", "61_90", "90_PLUS")


def receivables(tenant: uuid.UUID, book: str) -> list[dict[str, Any]]:
    b = BOOK_SQL[book]
    buckets = ", ".join(
        f"coalesce(sum(d.outstanding) FILTER (WHERE d.ageing_bucket = '{k}'), 0)"
        f" AS bucket_{k.lower()}"
        for k in BUCKETS
    )
    return _rows(
        f"""SELECT d.party_id, p.display_name, count(*)::int AS document_count,
                   {buckets}, sum(d.outstanding) AS total
              FROM v_receivables d
              JOIN parties p ON p.tenant_id = d.tenant_id AND p.id = d.party_id
             WHERE d.tenant_id = %s AND {b}
             GROUP BY d.party_id, p.display_name
             ORDER BY total DESC, p.display_name""",  # noqa: S608
        [tenant],
    )


def projects(tenant: uuid.UUID, project: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Per project: billing (v_project_billing) plus costs. Expense GST is a
    cost unless input tax credit can be claimed (itc_eligible)."""
    where = "AND v.project_id = %s" if project else ""
    params: list[Any] = [tenant] + ([project] if project else [])
    return _rows(
        f"""SELECT v.project_id, v.code, v.name, v.contract_value, v.billed_taxable,
                   v.retention_held, v.retention_released, v.tds_deducted,
                   v.advance_recovered, v.outstanding,
                   coalesce(e.cost, 0) AS cost,
                   v.billed_taxable - coalesce(e.cost, 0) AS margin
              FROM v_project_billing v
              LEFT JOIN (
                   SELECT tenant_id, project_id,
                          sum(taxable_value + CASE WHEN itc_eligible THEN 0 ELSE gst_amount END)
                            AS cost
                     FROM expenses WHERE status = 'RECORDED' AND project_id IS NOT NULL
                    GROUP BY tenant_id, project_id
              ) e ON e.tenant_id = v.tenant_id AND e.project_id = v.project_id
             WHERE v.tenant_id = %s {where}
             ORDER BY v.code""",  # noqa: S608
        params,
    )


def gst_summary(tenant: uuid.UUID, start: date, end: date) -> list[dict[str, Any]]:
    """Outward supplies of GST documents by rate and B2B (recipient GSTIN) / B2C."""
    return _rows(
        f"""SELECT CASE WHEN coalesce(d.party_snapshot ->> 'gstin', '') <> ''
                        THEN 'B2B' ELSE 'B2C' END AS supply,
                   l.gst_rate,
                   count(DISTINCT d.id)::int AS document_count,
                   sum({SIGNED} * l.taxable_value) AS taxable_value,
                   sum({SIGNED} * l.cgst_amount) AS cgst,
                   sum({SIGNED} * l.sgst_amount) AS sgst,
                   sum({SIGNED} * l.igst_amount) AS igst,
                   sum({SIGNED} * l.cess_amount) AS cess
              FROM documents d
              JOIN document_lines l ON l.tenant_id = d.tenant_id AND l.document_id = d.id
             WHERE d.tenant_id = %s AND d.status = 'ISSUED' AND d.is_gst_document
               AND d.doc_date BETWEEN %s AND %s
             GROUP BY 1, 2 ORDER BY 1, 2""",  # noqa: S608
        [tenant, start, end],
    )


# Indian financial-year quarter of a date: Apr-Jun 1, Jul-Sep 2, Oct-Dec 3, Jan-Mar 4.
FY_QUARTER_SQL = (
    "((extract(month FROM d.doc_date)::int + 8) %% 12) / 3 + 1"  # %% : placeholder escape
)


def tds_reconciliation(
    tenant: uuid.UUID, fy_start_year: int, party: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Per client and quarter: income-tax TDS expected from our issued bills
    (by bill date: s.194C deducts when the client books the bill) against
    the TDS certificates (Form 16A) recorded."""
    party_sql = "AND d.party_id = %s" if party else ""
    cert_party_sql = "AND c.party_id = %s" if party else ""
    params: list[Any] = [tenant, fy_start_year, *([party] if party else [])]
    params += [tenant, fy_start_year, *([party] if party else []), tenant]
    return _rows(
        f"""WITH expected AS (
              SELECT d.party_id, {FY_QUARTER_SQL} AS quarter,
                     count(*)::int AS bill_count,
                     sum(d.subtotal) AS taxable_value,
                     sum(d.income_tax_tds_amount) AS expected
                FROM documents d
               WHERE d.tenant_id = %s AND d.status = 'ISSUED'
                 AND d.doc_type IN ('TAX_INVOICE', 'BILL_OF_SUPPLY')
                 AND d.income_tax_tds_amount > 0
                 AND d.fy_start_year = %s {party_sql}
               GROUP BY 1, 2
            ), certified AS (
              SELECT c.party_id, c.quarter::int AS quarter,
                     count(*)::int AS certificate_count,
                     sum(c.tds_amount) AS certified,
                     string_agg(DISTINCT c.deductor_tan, ', ') AS deductor_tans
                FROM tds_certificates c
               WHERE c.tenant_id = %s AND c.fy_start_year = %s {cert_party_sql}
               GROUP BY 1, 2
            )
            SELECT coalesce(e.party_id, c.party_id) AS party_id, p.display_name,
                   coalesce(e.quarter, c.quarter) AS quarter,
                   coalesce(e.bill_count, 0) AS bill_count,
                   coalesce(e.taxable_value, 0) AS taxable_value,
                   coalesce(e.expected, 0) AS expected,
                   coalesce(c.certificate_count, 0) AS certificate_count,
                   coalesce(c.certified, 0) AS certified,
                   c.deductor_tans
              FROM expected e
              FULL JOIN certified c ON c.party_id = e.party_id AND c.quarter = e.quarter
              JOIN parties p
                ON p.tenant_id = %s AND p.id = coalesce(e.party_id, c.party_id)
             ORDER BY 3, p.display_name""",  # noqa: S608 - fixed fragments
        params,
    )
