# Progress

Last updated: 2026-10-19

## Current phase

**Phase 0 — Foundations** (in progress): steps 1–5 of 8 done, step 6 mostly done.

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
- [x] Phase 0.4: `apps/core/tenancy.py` (`Principal`, `tenant_context()`: transaction-local `set_config`, refuses tenant switching, clears itself when nested) and `TenantContextMiddleware` (opens the request transaction, view's `ATOMIC_REQUESTS` nests as a savepoint; tenant only from `request.principal`). Tests with real commits: context gone after commit, no leak across requests on the same pooled connection, RLS read/write/update isolation, composite-FK cross-tenant reference blocked, failing view rolls back. Mutation-checked (session-level `set_config` makes 3 tests fail). 49 tests
- [x] Phase 0.5: auth — signup (user + tenant + OWNER), login with generic errors, timing-equalised unknown emails and progressive lockout, Argon2id, JWT access tokens (HS256, 10 min, `kid`), opaque refresh tokens stored as SHA-256 and rotated with reuse detection (row-locked; concurrency-tested), per-request session liveness (instant logout/revoke), web cookie vs mobile body, switch-tenant, sessions list/revoke, TOTP MFA (encrypted secret, replay-proof, 10 hashed one-time recovery codes, OWNER/ADMIN gated until enrolled, cannot disable), `/me`. OpenAPI schema documents every endpoint (generation must be warning-free). Schema change: `users.mfa_recovery_codes`, `users.mfa_last_used_step` (schema.sql + migration). Also fixed: error responses now roll back the request transaction (custom DRF handler lacked `set_rollback`); app role may read `django_migrations` so `runserver` works. 84 tests
- [x] Phase 0.6 (part): role/action matrix as data (`apps/core/permissions.py`: `can`, `require`, `HasAction`), tested cell by cell against architecture §3; member management `GET /members`, `PATCH /members/{id}` (role), `DELETE /members/{id}` (revoke) with owner protection, no self-modification, last-owner guard, immediate sign-out on revoke/role change, 404 across tenants. Mutation-checked. 111 tests

## In progress

- Phase 0.6: inviting members (`POST /members`) — **waiting for an owner decision** on the invitation model (see Open questions).

## Next

Phase 0 — Foundations, in order:

1. ~~`docker-compose.yml` + `.env.example`~~ (done)
2. ~~Django project skeleton~~ (done)
3. ~~Database roles and migrations mirroring `db/schema.sql`~~ (done)
4. ~~Tenant context middleware + `tenant_context()`~~ (done)
5. ~~Auth~~ (done; see deferred items below)
6. Memberships and role permissions
7. Port `db/tests` checks to pytest against real Postgres; add concurrency tests (parallel issue, parallel allocation)
8. GitHub Actions CI: lint, type-check, tests, `pip-audit`, `makemigrations --check`

Then Phase 1 — core billing (parties, projects, documents, tax engine, PDF).
Full roadmap: `docs/01-architecture.md` §9.

## Open questions (for the owner)

- **Invitations** (blocks the rest of step 6): add existing users directly, or invite with accept step (status INVITED; needs RLS changes so the invitee can see and accept), or email invitations with a token that also works for people without an account (needs email sending + schema).

- Are the first customers GST-registered, and above the ₹5 Cr e-invoicing threshold?
- Do site engineers need offline drafts on mobile in v1?
- Pricing / plan limits per tenant?

## Known gaps / notes

- Local dev uses **SeaweedFS** instead of MinIO: MinIO stopped publishing container images in 2025 (owner decision, 2026-10-19). Production remains AWS S3 / Cloudflare R2.
- Use `127.0.0.1`, not `localhost`, in local connection URLs: on Windows `localhost` resolves to IPv6 first and psycopg stalls until timeout.
- Two DB aliases: `default` = `billing_app_login` (all queries, RLS applies), `owner` = `billing_owner` (migrations only). `manage.py migrate` without `--database=owner` fails with "permission denied for table django_migrations" by design.
- Tests: `default` mirrors `owner`; `tests/conftest.py` overrides `django_db_setup` so the owner alias always gets a `test_` database (pytest-django alone would leave the mirror pointing at the real dev database).
- Tests needing real COMMITs use the `committed_db` fixture (no TRUNCATE flush; fresh tenant ids per test; the test DB is dropped at session end).
- **Auth items deferred** (need email sending, Redis or a schema decision): email verification (`verify-email`; architecture says it gates issuing documents), password forgot/reset, `PATCH /me`, Redis rate limits (login per IP, API per user, `RateLimit-*` headers), `Idempotency-Key` on signup (`idempotency_keys` requires a tenant and user, which do not exist yet at signup), HaveIBeenPwned check (Django's common-password list is used for now), sliding vs absolute session lifetime (sliding 30 days now).
- Signup reveals whether an email is registered (`422 email_taken`); login and reset do not. Revisit with email verification (send a "you already have an account" email instead).
- Layer 1 of isolation (a tenant-aware ORM manager) is not built yet; RLS + composite FKs already enforce isolation. Add it with the first tenant-scoped endpoints (Phase 1).
- `auth_sessions` has a `tenant_id` column but no RLS, by design (global table, read only by id / token hash).
- The app role has no privileges on `django_migrations`. `TransactionTestCase`-style flushes (TRUNCATE) will not work as the app role; concurrency tests in step 7 need their own setup/cleanup.
- Until JWT lands (step 5), unauthenticated API calls get 403 `permission_denied`; step 5 makes them 401.
- Compose publishes Postgres on host port **5433** and Redis on **6380**, because native PostgreSQL 17 and Redis Windows services already use 5432 / 6379 on the dev machine.

- Schema was tested on PGlite (single connection), so concurrency behaviour (row locks under parallel requests) still needs testing on real Postgres in Phase 0.
- Payables (vendor bills, payments to subcontractors) are deferred; expenses track their own payment for now.
