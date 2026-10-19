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
| `db/tests/` | Executable checks of the schema (PGlite = real Postgres 17 in WASM) |
| `backend/` | Django project (not created yet — Phase 0) |

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
- Every new endpoint gets a cross-tenant test (tenant B must get 404 on tenant A's objects).
- Keep `db/schema.sql` and the Django migrations in sync — change both or neither.

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
# Schema checks (needs Node 20+)
cd db/tests && npm install && npm test
```

Django commands will be added here when `backend/` is scaffolded.

## Repository

GitHub: https://github.com/Aaronpaul2006/Billing-software
