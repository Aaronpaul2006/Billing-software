"""A client's statement of account: what they were billed and what they paid,
in date order, with a running balance (docs/02-api-design.md §8).

What the client owes for a bill is its total less the retention and TDS
deducted (retention comes back as its own line when it is released; TDS goes
to the government on the client's behalf). The mobilisation advance is not
subtracted: the advance itself was a payment from the client, and a bill's
"advance recovered" only adjusts it against that payment. So for a bill

    debit = grand_total - retention - income-tax TDS - GST TDS
          = net_receivable + advance recovered

Credit notes are credits by the same rule; payments are credits for their
amount (allocated or not); released retention is a debit. Cancelled bills,
cancelled releases and voided payments count nowhere, like every report.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from apps.documents.pdf.render import inr

from .queries import _rows

ZERO = Decimal("0.00")

DOC_LABELS = {
    "TAX_INVOICE": "Tax invoice",
    "BILL_OF_SUPPLY": "Bill of supply",
    "DEBIT_NOTE": "Debit note",
    "CREDIT_NOTE": "Credit note",
}
MODE_LABELS = {
    "BANK_TRANSFER": "Bank transfer",
    "UPI": "UPI",
    "CHEQUE": "Cheque",
    "CASH": "Cash",
    "CARD": "Card",
    "OTHER": "Other",
}

# Same day: bills before the payments that settle them. Then in the order made.
ENTRIES_SQL = """
SELECT d.doc_type AS kind, d.id AS document_id, NULL::uuid AS payment_id,
       NULL::uuid AS retention_release_id, d.doc_number AS reference, d.doc_date AS on_date,
       d.created_at, d.grand_total - d.retention_amount - d.income_tax_tds_amount
                     - d.gst_tds_amount AS amount,
       d.retention_amount, d.income_tax_tds_amount + d.gst_tds_amount AS tds,
       d.advance_recovery_amount AS advance, d.is_ra_bill, d.ra_sequence,
       src.doc_number AS against, NULL::text AS mode, CASE WHEN d.doc_type = 'CREDIT_NOTE'
                                                         THEN 2 ELSE 0 END AS day_order
  FROM documents d
  LEFT JOIN documents src ON src.tenant_id = d.tenant_id AND src.id = d.original_document_id
 WHERE d.tenant_id = %(tenant)s AND d.party_id = %(party)s AND d.status = 'ISSUED'
   AND d.doc_type IN ('TAX_INVOICE', 'BILL_OF_SUPPLY', 'DEBIT_NOTE', 'CREDIT_NOTE')
   AND d.doc_date <= %(end)s
UNION ALL
SELECT 'RETENTION_RELEASE', NULL, NULL, r.id, r.reference, r.release_date, r.created_at,
       r.amount, 0, 0, 0, FALSE, NULL, NULL, NULL, 1
  FROM retention_releases r
 WHERE r.tenant_id = %(tenant)s AND r.party_id = %(party)s AND r.status = 'RELEASED'
   AND r.release_date <= %(end)s
UNION ALL
SELECT 'PAYMENT', NULL, p.id, NULL, p.reference, p.payment_date, p.created_at,
       p.amount, 0, 0, 0, FALSE, NULL, NULL, p.mode, 3
  FROM payments p
 WHERE p.tenant_id = %(tenant)s AND p.party_id = %(party)s AND p.status = 'RECORDED'
   AND p.payment_date <= %(end)s
 ORDER BY on_date, day_order, created_at
"""


def _describe(row: dict[str, Any]) -> str:
    kind = row["kind"]
    if kind == "PAYMENT":
        mode = MODE_LABELS.get(row["mode"], row["mode"])
        return f"Payment received · {mode}" + (f" · {row['reference']}" if row["reference"] else "")
    if kind == "RETENTION_RELEASE":
        return "Retention released" + (f" · {row['reference']}" if row["reference"] else "")
    text = f"{DOC_LABELS[kind]} {row['reference']}"
    if row["is_ra_bill"] and row["ra_sequence"]:
        text += f" · RA bill {row['ra_sequence']}"
    if kind == "CREDIT_NOTE" and row["against"]:
        text += f" · against {row['against']}"
    less = []
    if row["retention_amount"]:
        less.append(f"retention {inr(row['retention_amount'])}")
    if row["tds"]:
        less.append(f"TDS {inr(row['tds'])}")
    if less:
        text += f" (less {' and '.join(less)})"
    if row["advance"]:
        text += f" · advance {inr(row['advance'])} adjusted"
    return text


def build_statement(tenant: uuid.UUID, party: uuid.UUID, start: date, end: date) -> dict[str, Any]:
    """Opening balance on `start`, the entries from `start` to `end`, closing balance.
    A positive balance is what the client owes; negative, what they paid ahead."""
    rows = _rows(ENTRIES_SQL, {"tenant": tenant, "party": party, "end": end})
    opening = ZERO
    balance = ZERO
    entries: list[dict[str, Any]] = []
    total_debit = total_credit = ZERO
    for row in rows:
        credit_side = row["kind"] in ("CREDIT_NOTE", "PAYMENT")
        debit = ZERO if credit_side else row["amount"]
        credit = row["amount"] if credit_side else ZERO
        if row["on_date"] < start:
            opening += debit - credit
            balance = opening
            continue
        balance += debit - credit
        total_debit += debit
        total_credit += credit
        entries.append(
            {
                "date": row["on_date"],
                "kind": row["kind"],
                "reference": row["reference"],
                "description": _describe(row),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "document_id": row["document_id"],
                "payment_id": row["payment_id"],
                "retention_release_id": row["retention_release_id"],
            }
        )
    return {
        "from": start,
        "to": end,
        "opening_balance": opening,
        "entries": entries,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "closing_balance": opening + total_debit - total_credit,
    }
