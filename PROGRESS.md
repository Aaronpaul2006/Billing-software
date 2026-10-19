# Progress

Last updated: 2026-10-19

## Current phase

**Phase 0 — Foundations** (in progress): steps 1–3 of 8 done.

## Done

- [x] Concept review and critique of the original idea (`Project billling software.docx`)
- [x] Decided stack: Django + DRF, PostgreSQL 17+, Celery/Redis, multi-tenant from day one
- [x] Multi-tenant data model with RLS, composite FKs, integrity triggers, audit trail, reporting views — `db/schema.sql`
- [x] Schema verification suite: 32 checks passing (isolation, document lifecycle, settlements, audit) — `db/tests/`
- [x] Architecture document — `docs/01-architecture.md`
- [x] API design document — `docs/02-api-design.md`
- [x] `CLAUDE.md` project rules for Claude Code / IDE
- [x] Git repository connected to GitHub
- [x] Phase 0.1: `docker-compose.yml` (Postgres 17.11, Redis 8.10, SeaweedFS 4.48 for S3, Mailpit 1.31) and `.env.example`; all services healthy, smoke-checked (auth required on Redis and S3, private bucket, SMTP → Mailpit)
- [x] Phase 0.2: Django 5.2 LTS skeleton in `backend/`: uv lockfile (Python 3.14), settings base/dev/test/prod from env, DRF (secure-by-default permissions, JSON only, money as string), drf-spectacular OpenAPI 3.1 at `/api/v1/schema/`, RFC 9457 problem+json errors with server-generated UUIDv7 `request_id`, `/healthz` + `/readyz`, `ATOMIC_REQUESTS`, Argon2 hasher, prod settings refuse weak secrets; ruff, mypy (strict), pytest (19 tests), pip-audit clean, `check --deploy` clean
- [x] Phase 0.3: database roles (`scripts/bootstrap_db.py`: `billing_owner` runs migrations, `billing_app_login` ∈ `billing_app` serves the API, NOBYPASSRLS, owns nothing) and migrations for all 17 tables (11 apps). Models mirror `db/schema.sql` column for column; composite FKs, triggers, audit trail, RLS, views and grants in RunSQL. Router: migrations only through the `owner` alias. `tests/db/test_schema_sync.py` proves migrations ≡ `schema.sql` across 12 catalog categories; invariant tests: every tenant table RLS-forced, every view security_invoker, fail-closed without context, app role cannot migrate / write audit / update `amount_settled`. 37 tests

## In progress

- Phase 0.4: tenant context middleware and `tenant_context()` helper.

## Next

Phase 0 — Foundations, in order:

1. ~~`docker-compose.yml` + `.env.example`~~ (done)
2. ~~Django project skeleton~~ (done)
3. ~~Database roles and migrations mirroring `db/schema.sql`~~ (done)
4. Tenant context middleware + `tenant_context()` helper for Celery/tests
5. Auth: signup, login, Argon2id, JWT access + rotating refresh tokens, TOTP MFA for owners/admins
6. Memberships and role permissions
7. Port `db/tests` checks to pytest against real Postgres; add concurrency tests (parallel issue, parallel allocation)
8. GitHub Actions CI: lint, type-check, tests, `pip-audit`, `makemigrations --check`

Then Phase 1 — core billing (parties, projects, documents, tax engine, PDF).
Full roadmap: `docs/01-architecture.md` §9.

## Open questions (for the owner)

- Are the first customers GST-registered, and above the ₹5 Cr e-invoicing threshold?
- Do site engineers need offline drafts on mobile in v1?
- Pricing / plan limits per tenant?

## Known gaps / notes

- Local dev uses **SeaweedFS** instead of MinIO: MinIO stopped publishing container images in 2025 (owner decision, 2026-10-19). Production remains AWS S3 / Cloudflare R2.
- Use `127.0.0.1`, not `localhost`, in local connection URLs: on Windows `localhost` resolves to IPv6 first and psycopg stalls until timeout.
- Two DB aliases: `default` = `billing_app_login` (all queries, RLS applies), `owner` = `billing_owner` (migrations only). `manage.py migrate` without `--database=owner` fails with "permission denied for table django_migrations" by design.
- Tests: `default` mirrors `owner`; `tests/conftest.py` overrides `django_db_setup` so the owner alias always gets a `test_` database (pytest-django alone would leave the mirror pointing at the real dev database).
- `auth_sessions` has a `tenant_id` column but no RLS, by design (global table, read only by id / token hash).
- The app role has no privileges on `django_migrations`. `TransactionTestCase`-style flushes (TRUNCATE) will not work as the app role; concurrency tests in step 7 need their own setup/cleanup.
- Until JWT lands (step 5), unauthenticated API calls get 403 `permission_denied`; step 5 makes them 401.
- Compose publishes Postgres on host port **5433** and Redis on **6380**, because native PostgreSQL 17 and Redis Windows services already use 5432 / 6379 on the dev machine.

- Schema was tested on PGlite (single connection), so concurrency behaviour (row locks under parallel requests) still needs testing on real Postgres in Phase 0.
- Payables (vendor bills, payments to subcontractors) are deferred; expenses track their own payment for now.
