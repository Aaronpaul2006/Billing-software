"""Client-portal sessions (W.5): the database itself limits a CLIENT session
to its own client's issued rows (db/schema.sql §8, client_scope policies).

Raw SQL as the app role, like the other database-rule tests: these check the
policies, independent of the API's permission checks.
"""

import uuid
from contextlib import AbstractContextManager

import pytest
from django.db import DatabaseError, transaction

from apps.core.tenancy import TenantContext, tenant_context

from .seed import Seeded, add_line, issue, issued_invoice, new_draft, rowcount, seed_tenant, sql

pytestmark = pytest.mark.django_db


@pytest.fixture
def a() -> Seeded:
    return seed_tenant("A", "32ABCDE1234F1Z5", "32")


def _ids(query: str) -> set[uuid.UUID]:
    return {r[0] for r in sql(query)}


def _fails(statement: str, params: list[object]) -> bool:
    try:
        with transaction.atomic():
            sql(statement, params)
    except DatabaseError:
        return True
    return False


class World:
    """Tenant A with clients X (a.party) and Y, each with a project, a BOQ item
    and an issued invoice; X also has a draft, a payment and an allocation."""

    def __init__(self, a: Seeded) -> None:
        self.a = a
        self.x = a.party
        self.y = uuid.uuid7()
        self.y_project = uuid.uuid7()
        self.x_doc = a.doc
        self.x_draft = uuid.uuid7()
        self.y_doc = uuid.uuid7()
        self.x_payment = uuid.uuid7()
        self.y_payment = uuid.uuid7()
        self.client = uuid.uuid7()
        with tenant_context(a.tenant, a.user):
            issued_invoice(a)
            new_draft(a, self.x_draft)
            sql(
                "INSERT INTO parties (id, tenant_id, display_name, gst_treatment, created_by)"
                " VALUES (%s, %s, 'Client Y', 'UNREGISTERED', %s)",
                [self.y, a.tenant, a.user],
            )
            sql(
                "INSERT INTO projects (id, tenant_id, code, name, client_party_id,"
                " gst_registration_id, site_state_code, created_by)"
                " VALUES (%s, %s, 'P2', 'Tower', %s, %s, '32', %s)",
                [self.y_project, a.tenant, self.y, a.reg, a.user],
            )
            for project in (a.project, self.y_project):
                sql(
                    "INSERT INTO boq_items (tenant_id, project_id, item_code, description, unit,"
                    " contract_qty, rate) VALUES (%s, %s, '1', 'Excavation', 'cum', 10, 100)",
                    [a.tenant, project],
                )
            sql(
                "INSERT INTO documents (id, tenant_id, doc_type, gst_registration_id, doc_date,"
                " party_id, project_id, place_of_supply, supply_type, created_by)"
                " VALUES (%s, %s, 'TAX_INVOICE', %s, '2026-10-19', %s, %s, '32', 'INTRA_STATE', %s)",
                [self.y_doc, a.tenant, a.reg, self.y, self.y_project, a.user],
            )
            add_line(a, self.y_doc)
            sql(
                "UPDATE documents SET subtotal = 10000, cgst_amount = 900, sgst_amount = 900,"
                " grand_total = 11800, net_receivable = 11800 WHERE id = %s",
                [self.y_doc],
            )
            issue(a, self.y_doc, "INV/0002")
            for payment, party in ((self.x_payment, self.x), (self.y_payment, self.y)):
                sql(
                    "INSERT INTO payments (id, tenant_id, party_id, payment_date, amount, mode,"
                    " created_by) VALUES (%s, %s, %s, '2026-10-20', 5000, 'UPI', %s)",
                    [payment, a.tenant, party, a.user],
                )
            for doc, payment in ((self.x_doc, self.x_payment), (self.y_doc, self.y_payment)):
                sql(
                    "INSERT INTO allocations (tenant_id, document_id, payment_id, amount,"
                    " created_by) VALUES (%s, %s, %s, 5000, %s)",
                    [a.tenant, doc, payment, a.user],
                )
            sql(
                "INSERT INTO users (id, email, password_hash, full_name)"
                " VALUES (%s, %s, 'argon2id$x', 'Client person')",
                [self.client, f"{self.client.hex}@example.com"],
            )
            sql(
                "INSERT INTO memberships (tenant_id, user_id, role, party_id)"
                " VALUES (%s, %s, 'CLIENT', %s)",
                [a.tenant, self.client, self.x],
            )

    def as_client(self) -> AbstractContextManager[TenantContext]:
        return tenant_context(self.a.tenant, self.client, party_id=self.x)


@pytest.fixture
def w(a: Seeded) -> World:
    return World(a)


def test_client_session_sees_only_its_clients_issued_rows(w: World) -> None:
    with w.as_client():
        assert _ids("SELECT id FROM parties") == {w.x}
        assert _ids("SELECT id FROM projects") == {w.a.project}
        assert _ids("SELECT project_id FROM boq_items") == {w.a.project}
        assert _ids("SELECT id FROM documents") == {w.x_doc}  # not the draft, not Y's
        assert _ids("SELECT document_id FROM document_lines") == {w.x_doc}
        assert _ids("SELECT id FROM payments") == {w.x_payment}
        assert _ids("SELECT document_id FROM allocations") == {w.x_doc}
        assert _ids("SELECT document_id FROM v_receivables") == {w.x_doc}
        assert _ids("SELECT project_id FROM v_project_billing") == {w.a.project}
        assert _ids("SELECT user_id FROM memberships") == {w.client}
        assert _ids("SELECT id FROM tenants") == {w.a.tenant}  # the business's name
        for table in ("gst_registrations", "document_series", "catalog_items", "audit_log"):
            assert sql(f"SELECT count(*) FROM {table}")[0][0] == 0, table  # noqa: S608


def test_staff_sessions_are_unaffected(w: World) -> None:
    with tenant_context(w.a.tenant, w.a.user):
        assert _ids("SELECT id FROM parties") == {w.x, w.y}
        assert _ids("SELECT id FROM documents") == {w.x_doc, w.x_draft, w.y_doc}
        assert _ids("SELECT id FROM payments") == {w.x_payment, w.y_payment}
        assert sql("SELECT count(*) FROM audit_log")[0][0] > 0


def test_client_session_cannot_write_outside_its_scope(w: World) -> None:
    with w.as_client():
        # another client's rows are invisible, so untouchable
        assert rowcount("UPDATE parties SET display_name = 'x' WHERE id = %s", [w.y]) == 0
        assert rowcount("UPDATE tenants SET legal_name = 'x'") == 0
        # new rows must stay inside the scope: no drafts, no other client's party
        assert _fails(
            "INSERT INTO documents (tenant_id, doc_type, gst_registration_id, doc_date, party_id,"
            " place_of_supply, supply_type, created_by)"
            " VALUES (%s, 'QUOTATION', %s, '2026-10-19', %s, '32', 'INTRA_STATE', %s)",
            [w.a.tenant, w.a.reg, w.x, w.client],
        )
        assert _fails(
            "INSERT INTO parties (tenant_id, display_name, gst_treatment, created_by)"
            " VALUES (%s, 'Mine now', 'UNREGISTERED', %s)",
            [w.a.tenant, w.client],
        )


def test_client_membership_must_name_a_party_of_its_own_tenant(w: World) -> None:
    other = seed_tenant("B", "29ABCDE1234F1Z9", "29")
    with tenant_context(w.a.tenant, w.a.user):
        user = uuid.uuid7()
        sql(
            "INSERT INTO users (id, email, password_hash, full_name)"
            " VALUES (%s, %s, 'argon2id$x', 'Someone')",
            [user, f"{user.hex}@example.com"],
        )
        insert = (
            "INSERT INTO memberships (tenant_id, user_id, role, party_id) VALUES (%s, %s, %s, %s)"
        )
        assert _fails(insert, [w.a.tenant, user, "CLIENT", None])  # a client needs its party
        assert _fails(insert, [w.a.tenant, user, "VIEWER", w.x])  # staff have none
        assert _fails(insert, [w.a.tenant, user, "CLIENT", other.party])  # B's client: FK


def test_every_table_with_row_security_has_a_client_scope_policy() -> None:
    rows = sql(
        """SELECT c.relname,
                  EXISTS (SELECT 1 FROM pg_policies p
                           WHERE p.tablename = c.relname AND p.policyname = 'client_scope'
                             AND p.permissive = 'RESTRICTIVE')
             FROM pg_class c
            WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
              AND c.relrowsecurity"""
    )
    assert len(rows) >= 20
    missing = sorted(table for table, has in rows if not has)
    assert not missing, f"add a client_scope policy (db/schema.sql §8) to: {missing}"
