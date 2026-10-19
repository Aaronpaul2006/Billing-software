# CLAUDE.md — Construction Billing Platform

Instructions for Claude Code (terminal, desktop or IDE extension) working in
this repository. Read this first, then `PROGRESS.md` to see where things stand.

## What this project is

A multi-tenant, cloud-based billing and business-management SaaS for Indian
construction companies and contractors: quotations/estimates, GST tax invoices,
bills of supply, credit/debit notes, RA (running account) bills against a BOQ,
retention, TDS, payments, expenses, and owner dashboards. Web app + owner mobile
app on one REST API. Long-term project; the backend is being built first.

Original concept: `Project billling software.docx`.

## Where things are

| Path | What |
|---|---|
| `PROGRESS.md` | **What is done and what is next. Update it at every milestone.** |
| `docs/01-architecture.md` | Stack, multi-tenancy, roles, document lifecycle, tax engine, security, roadmap |
| `docs/02-api-design.md` | REST conventions and endpoint surface |
| `db/schema.sql` | Source-of-truth data model: tables, RLS, triggers, views, grants |
| `db/tests/` | Quick checks of `schema.sql` alone (PGlite = Postgres 17 in WASM, no Docker). The full rule suite runs in pytest: `backend/tests/db/` |
| `docker-compose.yml` | Local dev services: Postgres 5433, Redis 6380, SeaweedFS (S3) 8333, Mailpit 1025/8025 |
| `backend/` | Django project: `config/` (settings base/dev/test/prod, urls), `apps/` (one Django app per module), `tests/` |
| `backend/apps/core/db.py` | Field types / lookups that make models produce exactly `db/schema.sql` |
| `backend/apps/core/migrations/0003_database_security.py` | Composite FKs, triggers, RLS, views, grants (frozen copy of `schema.sql` §7–§10) |
| `backend/scripts/bootstrap_db.py` | Creates the roles `billing_owner`, `billing_app`, `billing_app_login` (run once per cluster, as superuser) |

## Stack (decided, do not change without asking)

Python 3.13+, Django LTS + Django REST Framework, PostgreSQL 17+, Celery + Redis,
S3-compatible storage, drf-spectacular (OpenAPI), Docker Compose for local dev.

## Non-negotiable rules

**Multi-tenancy** (see architecture §2.4 — each of these is a known leak):
- Every tenant table has `tenant_id`, RLS enabled **and forced**, policy `tenant_id = app_current_tenant()`.
- Every FK between tenant tables is composite: `(tenant_id, x_id) → parent (tenant_id, id)`.
- Tenant context is set only with `set_config('app.tenant_id', ..., true)` inside a transaction — never plain `SET`.
- The tenant comes from the access token's `tid` claim, never from a URL/header the client controls.
- The app connects as `billing_app` (not owner, NOBYPASSRLS). Migrations run as `billing_owner`.
- Every view is `WITH (security_invoker = true)`.
- Another tenant's object → **404**, never 403.

**Money & documents:**
- Money is `Decimal` / `numeric(14,2)`, never float. Quantize with `ROUND_HALF_UP`. Money is a **string** in JSON.
- Issued documents are immutable — corrections are credit/debit notes. Nothing financial is hard-deleted.
- Numbers are assigned at issue, using a `SELECT ... FOR UPDATE` lock on the series row. Never `MAX()+1`.
- Place of supply for construction = the project's site state.
- GST rates are data, never constants in code.
- No "parallel books": a REGULAR registration issues TAX_INVOICE, never BILL_OF_SUPPLY for taxable supplies.

**Code style:**
- Thin views, business rules in `services/` (plain functions), pure tax engine with no Django imports.
- Serializers list fields explicitly (no `__all__`).
- Every new endpoint gets a cross-tenant test (tenant B must get 404 on tenant A's objects):
  register it in `tests/tenancy/test_cross_tenant_endpoints.py` (the test fails for
  any unregistered `/api/v1` route).
- Business tables use `TenantScoped` (`apps/core/managers.py`): `Model.objects` is
  tenant-filtered and raises without a tenant context.
- Money / quantity / rate fields in serializers: `MoneyField`, `QuantityField`,
  `PercentField` (`apps/core/fields.py`) — they reject JSON numbers.
- Editable resources: `ETag` on responses, `If-Match` on changes, version bumped with
  `update_versioned()` (`apps/core/versioning.py`).
- Money-moving POSTs: decorate the handler with `@idempotent` (`apps/core/idempotency.py`).
- Services raise `apps.core.errors` (`NotFound`, `Conflict`, `Invalid`, ...), never DRF
  exceptions; each has a stable `code`.
- Keep `db/schema.sql` and the Django migrations in sync — change both or neither.
  `tests/db/test_schema_sync.py` builds a database from each and compares the catalogs;
  it fails on any difference. Model FKs use `ref()` (`db_constraint=False`); the real
  (composite) FK constraints are added in RunSQL.

## Workflow rules

1. **Plan → build → test → update PROGRESS.md → commit → push.** At the end of each
   important step (a completed roadmap item, a working feature with passing
   tests, a schema change, a docs milestone), commit and **push to GitHub**
   (`origin`, branch `main`). The owner has asked for this standing workflow;
   no need to ask before each push.
2. **Update `PROGRESS.md` in the same commit** as the work it describes:
   move items to Done, set what's in progress, refresh Next steps.
3. Run the tests before every push. Never push a red build to `main`.
4. Never commit secrets: `.env`, keys, tokens, database dumps. Use `.env.example`
   for documentation of variables.
5. Commit messages: imperative, scoped, e.g. `schema: add retention release`,
   `docs: describe e-invoice flow`, `auth: refresh token rotation`.
6. Small, focused commits. If a step can't be finished, record the state in
   `PROGRESS.md` rather than leaving it undocumented.

## Commands

```bash
# Local services (Docker Desktop must be running)
cp .env.example .env
docker compose up -d --wait
docker compose down            # add -v to wipe the data volumes

# Schema checks (needs Node 20+)
cd db/tests && npm install && npm test
```

# Backend (run inside backend/; needs uv and the compose services up)
uv sync                                  # install exact versions from uv.lock
uv run python scripts/bootstrap_db.py    # once per Postgres cluster: roles + db owner
uv run python manage.py migrate --database=owner   # migrations run ONLY as billing_owner
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest
uv run python manage.py runserver        # dev settings; docs at /api/v1/docs/
uv run python manage.py makemigrations --check --dry-run
```

Use `127.0.0.1`, not `localhost`, in connection URLs: on Windows `localhost`
tries IPv6 `::1` first and stalls, while compose publishes on IPv4 only.

```bash

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every PR: ruff,
mypy, migrations check + fresh migrate, pytest on real Postgres, pip-audit,
and the PGlite schema checks. Run the same locally before pushing.

## Repository

GitHub: https://github.com/Aaronpaul2006/Billing-software
