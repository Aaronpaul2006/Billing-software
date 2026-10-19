"""Raw-SQL seeding for database-rule tests, as the app role, like the API would.

Ported from db/tests/schema.test.mjs. Raw SQL on purpose: these tests check
the database's own rules (RLS, triggers, constraints), independent of the ORM.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from django.db import connection

from apps.core.tenancy import tenant_context


def sql(query: str, params: list[Any] | tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(query, list(params))
        return list(cursor.fetchall()) if cursor.description else []


def rowcount(query: str, params: list[Any] | tuple[Any, ...] = ()) -> int:
    with connection.cursor() as cursor:
        cursor.execute(query, list(params))
        return int(cursor.rowcount)


@dataclass
class Seeded:
    tenant: uuid.UUID
    user: uuid.UUID
    reg: uuid.UUID = field(default_factory=uuid.uuid7)
    party: uuid.UUID = field(default_factory=uuid.uuid7)
    project: uuid.UUID = field(default_factory=uuid.uuid7)
    series: uuid.UUID = field(default_factory=uuid.uuid7)
    doc: uuid.UUID = field(default_factory=uuid.uuid7)
    state: str = "32"


def seed_tenant(key: str, gstin: str, state: str) -> Seeded:
    """User, tenant, OWNER membership, REGULAR registration, party, project,
    TAX_INVOICE series 2026 "INV/", and one draft invoice."""
    s = Seeded(tenant=uuid.uuid7(), user=uuid.uuid7(), state=state)
    with tenant_context(s.tenant, s.user):
        sql(
            "INSERT INTO users (id, email, password_hash, full_name)"
            " VALUES (%s, %s, 'argon2id$x', 'User ' || %s)",
            [s.user, f"{s.user.hex}@example.com", key],
        )
        sql("INSERT INTO tenants (id, legal_name) VALUES (%s, 'Builder ' || %s)", [s.tenant, key])
        sql(
            "INSERT INTO memberships (tenant_id, user_id, role) VALUES (%s, %s, 'OWNER')",
            [s.tenant, s.user],
        )
        sql(
            "INSERT INTO gst_registrations (id, tenant_id, registration_type, gstin, state_code,"
            " legal_name, address, is_default)"
            " VALUES (%s, %s, 'REGULAR', %s, %s, 'Builder', '{}', true)",
            [s.reg, s.tenant, gstin, state],
        )
        sql(
            "INSERT INTO parties (id, tenant_id, display_name, gst_treatment, state_code,"
            " created_by)"
            " VALUES (%s, %s, 'Client of ' || %s, 'UNREGISTERED', %s, %s)",
            [s.party, s.tenant, key, state, s.user],
        )
        sql(
            "INSERT INTO projects (id, tenant_id, code, name, client_party_id, gst_registration_id,"
            " site_state_code, retention_pct, created_by)"
            " VALUES (%s, %s, 'P1', 'Villa', %s, %s, %s, 5, %s)",
            [s.project, s.tenant, s.party, s.reg, state, s.user],
        )
        sql(
            "INSERT INTO document_series (id, tenant_id, gst_registration_id, doc_type,"
            " fy_start_year, prefix)"
            " VALUES (%s, %s, %s, 'TAX_INVOICE', 2026, 'INV/')",
            [s.series, s.tenant, s.reg],
        )
        new_draft(s, s.doc)
    return s


def new_draft(
    s: Seeded, doc: uuid.UUID, *, doc_date: str = "2026-10-19", place: str | None = None
) -> uuid.UUID:
    sql(
        "INSERT INTO documents (id, tenant_id, doc_type, gst_registration_id, doc_date, party_id,"
        " project_id, place_of_supply, supply_type, created_by)"
        " VALUES (%s, %s, 'TAX_INVOICE', %s, %s, %s, %s, %s, 'INTRA_STATE', %s)",
        [doc, s.tenant, s.reg, doc_date, s.party, s.project, place or s.state, s.user],
    )
    return doc


def add_line(s: Seeded, doc: uuid.UUID) -> None:
    """10 nos at Rs 1000, GST 18 %: taxable 10000, CGST 900, SGST 900, total 11800."""
    sql(
        "INSERT INTO document_lines (tenant_id, document_id, line_no, description, sac_hsn,"
        " quantity, rate, taxable_value, gst_rate, cgst_amount, sgst_amount, line_total)"
        " VALUES (%s, %s, 1, 'RCC work', '9954', 10, 1000, 10000, 18, 900, 900, 11800)",
        [s.tenant, doc],
    )


def set_totals(doc: uuid.UUID, subtotal: int = 10000) -> None:
    """Totals with 500 retention and 200 TDS: net receivable = subtotal + 1100."""
    sql(
        "UPDATE documents SET subtotal = %s::numeric, cgst_amount = 900, sgst_amount = 900,"
        " grand_total = %s::numeric + 1800, retention_amount = 500, income_tax_tds_amount = 200,"
        " net_receivable = %s::numeric + 1800 - 700 WHERE id = %s",
        [subtotal, subtotal, subtotal, doc],
    )


def issue(s: Seeded, doc: uuid.UUID, number: str = "INV/0001") -> None:
    sql(
        "UPDATE documents SET status = 'ISSUED', series_id = %s, doc_number = %s,"
        " issued_at = now(),"
        " issued_by = %s, supplier_snapshot = '{}', party_snapshot = '{}' WHERE id = %s",
        [s.series, number, s.user, doc],
    )


def issued_invoice(s: Seeded) -> uuid.UUID:
    """The seeded draft, with a line and correct totals, issued as INV/0001."""
    add_line(s, s.doc)
    set_totals(s.doc)
    issue(s, s.doc)
    return s.doc
