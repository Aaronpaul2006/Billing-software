"""Database rules, checked against real PostgreSQL as the app role.

Ported one-to-one from db/tests/schema.test.mjs (32 checks; PGlite). Each
check is its own test with freshly seeded tenants A and B. A statement that
must fail runs in its own savepoint, so the test can continue afterwards.
"""

import re
import uuid
from collections.abc import Callable
from decimal import Decimal
from functools import partial

import pytest
from django.db import DatabaseError, connections, transaction

from apps.core.tenancy import tenant_context, user_context

from .seed import (
    Seeded,
    add_line,
    issue,
    issued_invoice,
    new_draft,
    rowcount,
    seed_tenant,
    set_totals,
    sql,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def a() -> Seeded:
    return seed_tenant("A", "32ABCDE1234F1Z5", "32")


@pytest.fixture
def b() -> Seeded:
    return seed_tenant("B", "29ABCDE1234F1Z5", "29")


def fails(pattern: str, action: Callable[[], object]) -> str:
    """Run `action` in a savepoint; it must raise a database error matching `pattern`."""
    with pytest.raises(DatabaseError) as exc_info, transaction.atomic():
        action()
    message = str(exc_info.value)
    assert re.search(pattern, message), message
    return message


# --- 1. Tenant isolation ------------------------------------------------------------


def test_tenant_sees_only_its_own_parties(a: Seeded, b: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        assert sql("SELECT tenant_id FROM parties") == [(a.tenant,)]


def test_no_tenant_context_returns_zero_rows(a: Seeded, b: Seeded) -> None:
    with user_context(a.user):
        assert sql("SELECT count(*) FROM documents") == [(0,)]


def test_tenant_cannot_read_another_tenants_document_by_id(a: Seeded, b: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        assert sql("SELECT * FROM documents WHERE id = %s", [b.doc]) == []


def test_tenant_cannot_insert_rows_tagged_with_another_tenant(a: Seeded, b: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "row-level security",
            lambda: sql(
                "INSERT INTO parties (tenant_id, display_name, gst_treatment, created_by)"
                " VALUES (%s, 'x', 'CONSUMER', %s)",
                [b.tenant, a.user],
            ),
        )


def test_update_of_another_tenants_rows_affects_nothing(a: Seeded, b: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        assert rowcount("UPDATE parties SET display_name = 'hacked' WHERE id = %s", [b.party]) == 0


def test_cross_tenant_reference_blocked_by_composite_fk(a: Seeded, b: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "foreign key",
            lambda: sql(
                "INSERT INTO documents (tenant_id, doc_type, gst_registration_id, doc_date,"
                " party_id, place_of_supply, supply_type, created_by)"
                " VALUES (%s, 'QUOTATION', %s, '2026-10-19', %s, '32', 'INTRA_STATE', %s)",
                [a.tenant, a.reg, b.party, a.user],
            ),
        )


def test_without_tenant_user_sees_own_memberships_and_tenant_names(a: Seeded, b: Seeded) -> None:
    with user_context(a.user):
        assert sql("SELECT tenant_id FROM memberships") == [(a.tenant,)]
        assert sql("SELECT id FROM tenants") == [(a.tenant,)]


# --- 2. Document lifecycle ----------------------------------------------------------


def test_cannot_issue_without_lines(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails("no lines", lambda: issue(a, a.doc))


def test_documents_must_be_created_as_draft(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "created as DRAFT",
            lambda: sql(
                "INSERT INTO documents (tenant_id, doc_type, status, gst_registration_id, doc_date,"
                " party_id, place_of_supply, supply_type, created_by)"
                " VALUES (%s, 'QUOTATION', 'ISSUED', %s, '2026-10-19', %s, '32',"
                " 'INTRA_STATE', %s)",
                [a.tenant, a.reg, a.party, a.user],
            ),
        )


def test_line_arithmetic_is_checked(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "check constraint",
            lambda: sql(
                "INSERT INTO document_lines (tenant_id, document_id, line_no, description,"
                " quantity, rate, taxable_value, line_total)"
                " VALUES (%s, %s, 9, 'bad', 2, 100, 150, 150)",
                [a.tenant, a.doc],
            ),
        )


def test_cannot_issue_when_totals_differ_from_lines(a: Seeded) -> None:
    def attempt() -> None:
        add_line(a, a.doc)
        set_totals(a.doc, 9999)
        issue(a, a.doc)

    with tenant_context(a.tenant, a.user):
        fails("check constraint|do not match", attempt)


def test_igst_on_intra_state_document_is_rejected(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "check constraint",
            lambda: sql(
                "UPDATE documents SET igst_amount = 100, grand_total = grand_total + 100"
                " WHERE id = %s",
                [a.doc],
            ),
        )


def test_issue_a_correct_invoice(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        issued_invoice(a)
        assert sql(
            "SELECT fy_start_year, is_gst_document, net_receivable FROM documents WHERE id = %s",
            [a.doc],
        ) == [(2026, True, Decimal("11100.00"))]


def test_issued_invoice_cannot_be_edited(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        issued_invoice(a)
        fails(
            "cannot be edited",
            lambda: sql("UPDATE documents SET notes = 'changed' WHERE id = %s", [a.doc]),
        )


def test_issued_invoice_cannot_be_deleted(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        issued_invoice(a)
        fails("only drafts", lambda: sql("DELETE FROM documents WHERE id = %s", [a.doc]))


def test_lines_of_an_issued_invoice_are_frozen(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        issued_invoice(a)
        fails(
            "cannot be changed",
            lambda: sql(
                "UPDATE document_lines SET description = 'x' WHERE document_id = %s", [a.doc]
            ),
        )


def test_duplicate_invoice_number_in_same_fy_is_rejected(a: Seeded) -> None:
    def second_with_same_number() -> None:
        doc = new_draft(a, uuid.uuid7(), doc_date="2027-01-05")  # FY 2026 as well
        add_line(a, doc)
        set_totals(doc)
        issue(a, doc, "INV/0001")

    with tenant_context(a.tenant, a.user):
        issued_invoice(a)
        fails("duplicate key", second_with_same_number)


def test_wrong_supply_type_for_place_of_supply_rejected_at_issue(a: Seeded) -> None:
    def attempt() -> None:
        doc = new_draft(a, uuid.uuid7(), place="29")  # inter-state, but marked INTRA_STATE
        add_line(a, doc)
        set_totals(doc)
        issue(a, doc, "INV/0002")

    with tenant_context(a.tenant, a.user):
        fails("supply_type", attempt)


def test_bill_of_supply_cannot_carry_gst(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "check constraint",
            lambda: sql(
                "INSERT INTO documents (tenant_id, doc_type, gst_registration_id, doc_date,"
                " party_id, place_of_supply, supply_type, subtotal, cgst_amount, sgst_amount,"
                " grand_total, net_receivable, created_by)"
                " VALUES (%s, 'BILL_OF_SUPPLY', %s, '2026-10-19', %s, '32', 'INTRA_STATE',"
                " 100, 9, 9, 118, 118, %s)",
                [a.tenant, a.reg, a.party, a.user],
            ),
        )


# --- 3. Payments & settlement ---------------------------------------------------------


@pytest.fixture
def paid(a: Seeded) -> uuid.UUID:
    """Invoice INV/0001 (net receivable 11100), payment of 8000, 5000 allocated."""
    payment = uuid.uuid7()
    with tenant_context(a.tenant, a.user):
        issued_invoice(a)
        sql(
            "INSERT INTO payments (id, tenant_id, party_id, payment_date, amount, mode, created_by)"
            " VALUES (%s, %s, %s, '2026-10-20', 8000, 'UPI', %s)",
            [payment, a.tenant, a.party, a.user],
        )
        sql(
            "INSERT INTO allocations (tenant_id, document_id, payment_id, amount, created_by)"
            " VALUES (%s, %s, %s, 5000, %s)",
            [a.tenant, a.doc, payment, a.user],
        )
    return payment


def test_allocation_updates_amount_settled(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        assert sql("SELECT amount_settled FROM documents WHERE id = %s", [a.doc]) == [
            (Decimal("5000.00"),)
        ]


def test_allocating_more_than_the_payment_is_rejected(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "exceeds|duplicate key",
            lambda: sql(
                "INSERT INTO allocations (tenant_id, document_id, payment_id, amount, created_by)"
                " VALUES (%s, %s, %s, 3500, %s)",
                [a.tenant, a.doc, paid, a.user],
            ),
        )


def test_app_cannot_write_amount_settled_directly(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "permission denied",
            lambda: sql("UPDATE documents SET amount_settled = 0 WHERE id = %s", [a.doc]),
        )


def test_cannot_cancel_an_invoice_with_settlements(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "check constraint",
            lambda: sql(
                "UPDATE documents SET status = 'CANCELLED', cancelled_at = now(),"
                " cancelled_by = %s, cancel_reason = 'x' WHERE id = %s",
                [a.user, a.doc],
            ),
        )


def test_receivables_view_shows_outstanding_for_own_tenant_only(
    a: Seeded, b: Seeded, paid: uuid.UUID
) -> None:
    with tenant_context(a.tenant, a.user):
        assert sql("SELECT tenant_id, outstanding FROM v_receivables") == [
            (a.tenant, Decimal("6100.00"))
        ]


def test_billing_summary_view_respects_rls(a: Seeded, b: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(b.tenant, b.user):
        assert sql("SELECT * FROM v_billing_summary") == []


def test_unwind_allocation_then_cancel(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        sql("DELETE FROM allocations WHERE payment_id = %s", [paid])
        sql(
            "UPDATE documents SET status = 'CANCELLED', cancelled_at = now(), cancelled_by = %s,"
            " cancel_reason = 'wrong client' WHERE id = %s",
            [a.user, a.doc],
        )
        assert sql("SELECT status, amount_settled FROM documents WHERE id = %s", [a.doc]) == [
            ("CANCELLED", Decimal("0.00"))
        ]


# --- 4. Audit trail ---------------------------------------------------------------------


def test_every_change_is_audited_with_the_acting_user(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        [(rows, actors, mine)] = sql(
            "SELECT count(*), count(DISTINCT actor_user_id), bool_and(tenant_id = %s)"
            " FROM audit_log",
            [a.tenant],
        )
        assert rows >= 10
        assert actors == 1
        assert mine is True
        assert sql("SELECT DISTINCT actor_user_id FROM audit_log") == [(a.user,)]


def test_tenant_cannot_read_another_tenants_audit_rows(a: Seeded, b: Seeded) -> None:
    with tenant_context(b.tenant, b.user):
        assert sql("SELECT count(*) FROM audit_log WHERE tenant_id = %s", [a.tenant]) == [(0,)]


def test_app_cannot_delete_audit_rows(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails("permission denied", lambda: sql("DELETE FROM audit_log"))


def test_app_cannot_forge_audit_rows(a: Seeded) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "permission denied",
            lambda: sql(
                "INSERT INTO audit_log (tenant_id, action, table_name, row_id)"
                " VALUES (%s, 'INSERT', 'x', %s)",
                [a.tenant, a.tenant],
            ),
        )


@pytest.mark.django_db(databases=["default", "owner"])
def test_even_the_owner_cannot_rewrite_audit_rows() -> None:
    # The owner runs in its own (test) transaction and cannot see rows the app
    # connection wrote, so it writes its own row first; RLS on audit_log is
    # not forced, so the owner may insert. UPDATE / DELETE / TRUNCATE all fail.
    tenant = uuid.uuid7()
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            "INSERT INTO audit_log (tenant_id, action, table_name, row_id)"
            " VALUES (%s, 'INSERT', 'x', %s)",
            [tenant, tenant],
        )
        for statement in (
            "UPDATE audit_log SET actor_user_id = NULL",
            "DELETE FROM audit_log",
            "TRUNCATE audit_log",
        ):
            with (
                pytest.raises(DatabaseError, match="append-only"),
                transaction.atomic(using="owner"),
            ):
                cursor.execute(statement)


def test_payments_cannot_be_hard_deleted(a: Seeded, paid: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        fails("permission denied", lambda: sql("DELETE FROM payments WHERE id = %s", [paid]))


# --- 4. Retention releases (Phase 3.3) -------------------------------------------------


@pytest.fixture
def released(a: Seeded, paid: uuid.UUID) -> uuid.UUID:
    """A retention release of 1000 on A's project; 400 of the payment settles it."""
    release = uuid.uuid7()
    with tenant_context(a.tenant, a.user):
        sql(
            "INSERT INTO retention_releases (id, tenant_id, project_id, party_id, book,"
            " release_date, amount, created_by)"
            " VALUES (%s, %s, %s, %s, 'GST', '2026-11-05', 1000, %s)",
            [release, a.tenant, a.project, a.party, a.user],
        )
        sql(
            "INSERT INTO allocations (tenant_id, retention_release_id, payment_id, amount,"
            " created_by) VALUES (%s, %s, %s, 400, %s)",
            [a.tenant, release, paid, a.user],
        )
    return release


def test_release_allocations_update_amount_settled(a: Seeded, released: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        settled = "SELECT amount_settled FROM retention_releases WHERE id = %s"
        assert sql(settled, [released]) == [(Decimal("400.00"),)]
        assert rowcount("DELETE FROM allocations WHERE retention_release_id = %s", [released]) == 1
        assert sql(settled, [released]) == [(Decimal("0.00"),)]


def test_release_cannot_be_over_settled(a: Seeded, b: Seeded, released: uuid.UUID) -> None:
    payment = uuid.uuid7()
    with tenant_context(a.tenant, a.user):
        sql(
            "INSERT INTO payments (id, tenant_id, party_id, payment_date, amount, mode, created_by)"
            " VALUES (%s, %s, %s, '2026-11-06', 5000, 'UPI', %s)",
            [payment, a.tenant, a.party, a.user],
        )
        fails(
            "retention_releases_amount_settled_check|check constraint",
            lambda: sql(
                "INSERT INTO allocations (tenant_id, retention_release_id, payment_id, amount,"
                " created_by) VALUES (%s, %s, %s, 600.01, %s)",
                [a.tenant, released, payment, a.user],
            ),
        )


def test_allocation_targets_and_sources_for_releases(a: Seeded, released: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        fails(  # a document and a release at once
            "check constraint",
            lambda: sql(
                "INSERT INTO allocations (tenant_id, document_id, retention_release_id,"
                " payment_id, amount, created_by)"
                " SELECT %s, %s, %s, payment_id, 1, %s FROM allocations LIMIT 1",
                [a.tenant, a.doc, released, a.user],
            ),
        )
        fails(  # a credit note never settles a release (trigger or CHECK, whichever first)
            "check constraint|allocation source must be",
            lambda: sql(
                "INSERT INTO allocations (tenant_id, retention_release_id, credit_note_id,"
                " amount, created_by) VALUES (%s, %s, %s, 1, %s)",
                [a.tenant, released, a.doc, a.user],
            ),
        )


def test_app_cannot_edit_releases_or_their_settlement(a: Seeded, released: uuid.UUID) -> None:
    with tenant_context(a.tenant, a.user):
        for statement in (
            "UPDATE retention_releases SET amount_settled = 0 WHERE id = %s",
            "UPDATE retention_releases SET amount = 1 WHERE id = %s",
            "DELETE FROM retention_releases WHERE id = %s",
        ):
            fails("permission denied", partial(sql, statement, [released]))


def test_cancelled_release_cannot_be_settled_and_rls_hides_it(
    a: Seeded, b: Seeded, released: uuid.UUID
) -> None:
    with tenant_context(a.tenant, a.user):
        fails(
            "check constraint",  # still settled: cancel needs amount_settled = 0
            lambda: sql(
                "UPDATE retention_releases SET status = 'CANCELLED', cancelled_at = now(),"
                " cancel_reason = 'x' WHERE id = %s",
                [released],
            ),
        )
        sql("DELETE FROM allocations WHERE retention_release_id = %s", [released])
        sql(
            "UPDATE retention_releases SET status = 'CANCELLED', cancelled_at = now(),"
            " cancel_reason = 'x' WHERE id = %s",
            [released],
        )
        fails(
            "only open retention releases",
            lambda: sql(
                "INSERT INTO allocations (tenant_id, retention_release_id, payment_id, amount,"
                " created_by) SELECT %s, %s, id, 1, %s FROM payments LIMIT 1",
                [a.tenant, released, a.user],
            ),
        )
    with tenant_context(b.tenant, b.user):
        assert sql("SELECT count(*) FROM retention_releases") == [(0,)]
