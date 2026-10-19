"""Invariants from docs/01-architecture.md §2.4 that every future table and
view must keep. These check the live catalog, so a new migration that forgets
RLS, forces nothing, or adds a definer view fails here."""

from typing import Any

import pytest
from django.db import connection, connections, transaction

from apps.core.db_router import MigrationsAsOwnerRouter

pytestmark = pytest.mark.django_db(databases=["default"])

# audit_log: RLS enabled but not forced (rows are written by the SECURITY
# DEFINER trigger as the owner); the app role still only reads its tenant.
RLS_NOT_FORCED = {"audit_log"}
# Global tables that carry a tenant_id without being tenant-owned
# (db/schema.sql §8): auth_sessions.tenant_id is the tenant a login session is
# bound to; sessions are only ever read by primary key or token hash.
GLOBAL_WITH_TENANT_COLUMN = {"auth_sessions"}


def _rows(query: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params or [])
        return list(cursor.fetchall())


def test_app_connects_as_unprivileged_member_of_billing_app() -> None:
    [(user, is_member, superuser, bypass, owned)] = _rows(
        """SELECT current_user, pg_has_role(current_user, 'billing_app', 'MEMBER'),
                  rolsuper, rolbypassrls,
                  (SELECT count(*) FROM pg_class
                    WHERE relowner = r.oid AND relnamespace = 'public'::regnamespace)
             FROM pg_roles r WHERE rolname = current_user"""
    )
    assert user != "billing_owner"
    assert is_member is True
    assert superuser is False
    assert bypass is False
    assert owned == 0, "the app role must not own tables (owners bypass RLS)"


def test_every_tenant_table_has_rls_enabled_and_forced() -> None:
    rows = _rows(
        """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
             FROM pg_class c
            WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
              AND (EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                             AND a.attname = 'tenant_id' AND NOT a.attisdropped)
                   OR c.relname = 'tenants')"""
    )
    rows = [r for r in rows if r[0] not in GLOBAL_WITH_TENANT_COLUMN]
    assert len(rows) >= 15
    for table, enabled, forced in rows:
        assert enabled, f"{table}: RLS not enabled"
        assert forced or table in RLS_NOT_FORCED, f"{table}: RLS not forced"


def test_every_view_is_security_invoker() -> None:
    views = _rows(
        """SELECT relname, coalesce(reloptions, '{}') FROM pg_class
            WHERE relnamespace = 'public'::regnamespace AND relkind = 'v'"""
    )
    assert views
    for name, options in views:
        assert "security_invoker=true" in options, f"view {name} would bypass RLS"


def test_without_tenant_context_queries_fail_closed() -> None:
    with transaction.atomic():
        assert _rows("SELECT app_current_tenant()") == [(None,)]
        assert _rows("SELECT count(*) FROM documents") == [(0,)]
        assert _rows("SELECT count(*) FROM tenants") == [(0,)]


def test_app_role_cannot_write_audit_log_or_settlement_totals() -> None:
    [(insert_audit, update_settled, update_status)] = _rows(
        """SELECT has_table_privilege('billing_app', 'audit_log', 'INSERT'),
                  has_column_privilege('billing_app', 'documents', 'amount_settled', 'UPDATE'),
                  has_column_privilege('billing_app', 'documents', 'status', 'UPDATE')"""
    )
    assert insert_audit is False
    assert update_settled is False
    assert update_status is True


def test_migrations_only_run_through_the_owner_connection() -> None:
    router = MigrationsAsOwnerRouter()
    assert router.allow_migrate("owner", "documents") is True
    assert router.allow_migrate("default", "documents") is False
    assert connections["owner"].settings_dict["USER"] == "billing_owner"
