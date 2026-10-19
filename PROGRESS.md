# Progress

Last updated: 2026-10-19

## Current phase

**Phase 0 — Foundations** (in progress): step 1 of 8 done.

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

## In progress

- Phase 0.2: Django project skeleton under `backend/`.

## Next

Phase 0 — Foundations, in order:

1. ~~`docker-compose.yml` + `.env.example`~~ (done)
2. Django project skeleton under `backend/` (settings split, `uv` lockfile, ruff, mypy, pytest)
3. Database roles (`billing_owner`, `billing_app`) and the first migrations mirroring `db/schema.sql` (tables + RunSQL for RLS, triggers, composite FKs, grants)
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
- Compose publishes Postgres on host port **5433** and Redis on **6380**, because native PostgreSQL 17 and Redis Windows services already use 5432 / 6379 on the dev machine.

- Schema was tested on PGlite (single connection), so concurrency behaviour (row locks under parallel requests) still needs testing on real Postgres in Phase 0.
- Payables (vendor bills, payments to subcontractors) are deferred; expenses track their own payment for now.
