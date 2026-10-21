"""Create the database roles and hand the database to billing_owner.

Run once per Postgres cluster (local compose, CI) as a superuser. Safe to
re-run: roles are created if missing and their passwords re-applied.

    uv run python scripts/bootstrap_db.py

Roles (see db/schema.sql §0 and docs/01-architecture.md §2.4):
  billing_owner      LOGIN, owns the database and tables, runs migrations.
                     CREATEDB only so the test runner can create test databases.
  billing_app        NOLOGIN group: the privileges the API and workers get.
                     Not the owner, NOBYPASSRLS, so RLS always applies.
  <app login user>   LOGIN member of billing_app; what DATABASE_URL uses.

Credentials come from DATABASE_OWNER_URL and DATABASE_URL, the superuser from
DATABASE_ADMIN_URL. In production pass --production: the owner then gets no
CREATEDB (nothing there creates test databases).
"""

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

OWNER_ROLE = "billing_owner"
APP_GROUP = "billing_app"


def _load_dotenv() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _url_parts(name: str) -> tuple[str, str, str]:
    """(user, password, database) from a postgres:// URL in the environment."""
    url = urlsplit(os.environ[name])
    return unquote(url.username or ""), unquote(url.password or ""), url.path.lstrip("/")


def main() -> int:
    _load_dotenv()
    owner_user, owner_password, database = _url_parts("DATABASE_OWNER_URL")
    app_user, app_password, app_database = _url_parts("DATABASE_URL")
    if owner_user != OWNER_ROLE:
        sys.exit(f"DATABASE_OWNER_URL must connect as {OWNER_ROLE}, not {owner_user!r}")
    if app_user in {OWNER_ROLE, APP_GROUP} or not app_user:
        sys.exit("DATABASE_URL must use a dedicated login role, not the owner or the group")
    if app_database != database:
        sys.exit("DATABASE_URL and DATABASE_OWNER_URL must point at the same database")

    createdb = "NOCREATEDB" if "--production" in sys.argv[1:] else "CREATEDB"
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True) as conn:
        ensure_role(
            conn,
            OWNER_ROLE,
            f"LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE {createdb}",
            owner_password,
        )
        ensure_role(
            conn, APP_GROUP, "NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB", None
        )
        ensure_role(
            conn,
            app_user,
            "LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB INHERIT",
            app_password,
        )
        conn.execute(
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(APP_GROUP), sql.Identifier(app_user))
        )

        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [database]).fetchone()
        if exists:
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(database), sql.Identifier(OWNER_ROLE)
                )
            )
        else:
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(database), sql.Identifier(OWNER_ROLE)
                )
            )

    print(f"roles ready: {OWNER_ROLE}, {APP_GROUP}, {app_user}")
    print(f"database {database!r} owned by {OWNER_ROLE}")
    return 0


def ensure_role(conn: psycopg.Connection, name: str, options: str, password: str | None) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name]).fetchone()
    verb = "ALTER" if exists else "CREATE"
    stmt = sql.SQL(f"{verb} ROLE {{}} {options}").format(sql.Identifier(name))
    if password is not None:
        stmt = sql.SQL("{} PASSWORD {}").format(stmt, sql.Literal(password))
    conn.execute(stmt)


if __name__ == "__main__":
    raise SystemExit(main())
