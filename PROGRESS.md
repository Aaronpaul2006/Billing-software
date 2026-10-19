# Progress

Last updated: 2026-10-19

## Current phase

**Phase 0 — Foundations** (not started). Design is complete and verified.

## Done

- [x] Concept review and critique of the original idea (`Project billling software.docx`)
- [x] Decided stack: Django + DRF, PostgreSQL 17+, Celery/Redis, multi-tenant from day one
- [x] Multi-tenant data model with RLS, composite FKs, integrity triggers, audit trail, reporting views — `db/schema.sql`
- [x] Schema verification suite: 32 checks passing (isolation, document lifecycle, settlements, audit) — `db/tests/`
- [x] Architecture document — `docs/01-architecture.md`
- [x] API design document — `docs/02-api-design.md`
- [x] `CLAUDE.md` project rules for Claude Code / IDE
- [x] Git repository connected to GitHub

## In progress

- Nothing yet.

## Next

Phase 0 — Foundations, in order:

1. `docker-compose.yml`: Postgres 17, Redis, MinIO, Mailpit; `.env.example`
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

- Schema was tested on PGlite (single connection), so concurrency behaviour (row locks under parallel requests) still needs testing on real Postgres in Phase 0.
- Payables (vendor bills, payments to subcontractors) are deferred; expenses track their own payment for now.
