"""db/schema.sql and the Django migrations must produce the same database.

CLAUDE.md: "Keep db/schema.sql and the Django migrations in sync". This test
loads db/schema.sql into a scratch database and compares its catalog with the
migrated test database: columns, defaults, constraints, indexes, functions,
triggers, RLS flags, policies, views, extensions and privileges. Object
*names* are ignored where Django and PostgreSQL name things differently
(constraints, indexes), everything else must match exactly.
"""

import re
import uuid
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from django.db import connections
from psycopg import sql

SCHEMA_SQL = Path(__file__).resolve().parents[3] / "db" / "schema.sql"
DJANGO_ONLY_TABLES = {"django_migrations"}

CATALOG_QUERIES: dict[str, str] = {
    "columns": """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid), a.attgenerated, a.attidentity
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'v')
           AND a.attnum > 0 AND NOT a.attisdropped""",
    "constraints": """
        SELECT conrelid::regclass::text, contype, pg_get_constraintdef(oid)
          FROM pg_constraint
         WHERE connamespace = 'public'::regnamespace AND conrelid <> 0""",
    "indexes": """
        SELECT tablename, regexp_replace(indexdef, 'INDEX \\S+ ON', 'INDEX ON')
          FROM pg_indexes WHERE schemaname = 'public'""",
    "functions": """
        SELECT proname, pg_get_function_identity_arguments(oid), prosrc, prosecdef,
               provolatile, proconfig::text
          FROM pg_proc WHERE pronamespace = 'public'::regnamespace AND prokind = 'f'
           AND NOT EXISTS (SELECT 1 FROM pg_depend d
                            WHERE d.objid = pg_proc.oid AND d.deptype = 'e')""",
    "triggers": """
        SELECT tgrelid::regclass::text, pg_get_triggerdef(oid)
          FROM pg_trigger WHERE NOT tgisinternal""",
    "row_level_security": """
        SELECT relname, relrowsecurity, relforcerowsecurity
          FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'""",
    "policies": """
        SELECT tablename, policyname, permissive, roles::text, cmd, qual, with_check
          FROM pg_policies WHERE schemaname = 'public'""",
    "views": """
        SELECT c.relname, pg_get_viewdef(c.oid), c.reloptions::text
          FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'v'""",
    "extensions": "SELECT extname FROM pg_extension",
    "table_privileges": """
        SELECT table_name, privilege_type FROM information_schema.role_table_grants
         WHERE grantee = 'billing_app'""",
    "column_privileges": """
        SELECT table_name, column_name, privilege_type FROM information_schema.column_privileges
         WHERE grantee = 'billing_app'""",
    "schema_privileges": """
        SELECT nspname, coalesce(nspacl::text, '') FROM pg_namespace WHERE nspname = 'public'""",
}


def _conninfo(alias: str, dbname: str | None = None) -> str:
    s = connections[alias].settings_dict
    return psycopg.conninfo.make_conninfo(
        host=s["HOST"],
        port=s["PORT"],
        user=s["USER"],
        password=s["PASSWORD"],
        dbname=dbname or s["NAME"],
        connect_timeout=5,
    )


def _normalise(category: str, row: tuple[Any, ...]) -> tuple[Any, ...]:
    if category == "schema_privileges":
        # role names differ by environment only in the owner entry
        return (row[0], re.sub(r"=UC/\w+", "=UC/<owner>", row[1]))
    return row


def _snapshot(conninfo: str) -> dict[str, Counter[tuple[Any, ...]]]:
    snap: dict[str, Counter[tuple[Any, ...]]] = {}
    with psycopg.connect(conninfo) as conn:
        for category, query in CATALOG_QUERIES.items():
            rows = conn.execute(query).fetchall()
            snap[category] = Counter(
                _normalise(category, tuple(r))
                for r in rows
                if not (r and r[0] in DJANGO_ONLY_TABLES)
            )
    return snap


@pytest.fixture(scope="module")
def reference_db(django_db_setup: None, django_db_blocker: Any) -> Iterator[str]:
    """A scratch database built from db/schema.sql alone."""
    name = f"schema_ref_{uuid.uuid4().hex[:12]}"
    with django_db_blocker.unblock():
        admin = _conninfo("owner", "postgres")
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(_conninfo("owner", name), autocommit=True) as conn:
                conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            yield _conninfo("owner", name)
        finally:
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
                )


@pytest.fixture(scope="module")
def snapshots(
    reference_db: str, django_db_blocker: Any
) -> tuple[dict[str, Counter[tuple[Any, ...]]], dict[str, Counter[tuple[Any, ...]]]]:
    migrated_db = connections["owner"].settings_dict["NAME"]
    assert migrated_db.startswith("test_"), f"refusing to inspect non-test database {migrated_db}"
    with django_db_blocker.unblock():
        return _snapshot(reference_db), _snapshot(_conninfo("owner"))


@pytest.mark.parametrize("category", list(CATALOG_QUERIES))
def test_migrations_match_schema_sql(
    category: str,
    snapshots: tuple[dict[str, Counter[tuple[Any, ...]]], dict[str, Counter[tuple[Any, ...]]]],
) -> None:
    schema, migrated = snapshots
    only_in_schema = sorted((schema[category] - migrated[category]).elements(), key=str)
    only_in_migrations = sorted((migrated[category] - schema[category]).elements(), key=str)
    report = "\n".join(
        [f"  - schema.sql only: {r}" for r in only_in_schema]
        + [f"  + migrations only: {r}" for r in only_in_migrations]
    )
    assert not report, f"{category} differ:\n{report}"
