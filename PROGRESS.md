# Progress

Last updated: 2026-10-20

## Current phase

**Phase 3 — Construction** (in progress): steps 3.1–3.2 of 4 done. Phases 0, 1 and 2 complete.

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
- [x] Phase 0.6 (rest): invitations, invite + accept (owner decision 2026-10-19): `POST /members` invites an existing account (INVITED), `GET /invitations`, `POST /invitations/{id}/accept|decline`. Schema: `tenant_member_read` also covers INVITED; new function `respond_to_invitation()` (schema.sql + migration, sync test passes). 119 tests
- [x] Phase 0.7: all 32 `db/tests` checks ported to pytest on real Postgres (`tests/db/test_schema_rules.py`, independent tests, raw SQL as the app role), plus concurrency tests with two real connections and overlapping transactions (`tests/db/test_concurrency.py`): series-lock issue is unique and gapless, the unique index catches the unlocked anti-pattern, a failed issue leaves no gap, parallel allocations cannot overpay an invoice or spend a payment twice. Stable over repeated runs. 156 tests
- [x] Phase 0.8: GitHub Actions CI (`.github/workflows/ci.yml`): backend job with Postgres 17.11 + Redis 8.10 services runs `uv sync --locked`, ruff (lint + format), mypy, role bootstrap, `makemigrations --check`, migrations on a fresh database as `billing_owner`, pytest (all 156 tests incl. concurrency), pip-audit; a second job runs the PGlite `schema.sql` checks. Actions pinned to commit SHAs. Rehearsed locally step by step on a fresh database
- [x] Phase 1.1: API building blocks — tenant-aware manager `TenantScoped` on the 13 business tables (isolation layer 1: `objects` raises without a tenant context, `save()` refuses another tenant), cursor pagination `{results, next_cursor}` (limit ≤ 100), django-filter + allow-listed ordering, `MoneyField`/`QuantityField`/`PercentField` (reject JSON numbers), optimistic locking (`ETag`, `If-Match` 428/412 with `current`, compare-and-set `update_versioned`), `@idempotent` POSTs (replay, 422 on reuse, 428 if missing, nothing stored on failure, concurrent duplicates run once), cross-tenant test generated from the URL conf (unregistered routes fail). Mutation-checked. 183 tests
- [x] Phase 1.2: `GET/PATCH /tenant`, `/gst-registrations` (GSTIN with check digit, PAN consistency, state/address rules, one default, immutable identity), `/document-series` (one active per registration/type/FY, locked once used, doc type vs registration type, `next_doc_number`), all with ETag/If-Match; `apps/core/india.py` (state codes, GSTIN, PAN, PIN). Schema: `version` on tenants / gst_registrations / document_series / catalog_items, unique active series index (schema.sql + migrations). The tenant manager's filter is now a lazy expression (django-filter and drf-spectacular build querysets without a tenant). 224 tests
- [x] Phase 1.3: `/parties` (GST treatment ↔ GSTIN rules, state/PAN from GSTIN, merged-PATCH validation, `q` search, archive not delete), `/projects` (unique code, client must be a customer, active registration, site address in site state, client/registration/site state locked once documents exist), `/projects/{id}/boq-items` + `/boq-items/{id}` (unique item code, GST ≤ 50 %, delete only if never billed), `/catalog-items` (delete only if unused). Shared `versioned_patch` / `detail_response` / `get_or_404` helpers; all routes in the cross-tenant registry. BOQ CSV/XLSX import deferred. 253 tests
- [x] Phase 1.4: tax engine `apps/documents/tax/` — pure Python (test forbids Django imports), Decimal + ROUND_HALF_UP, per-line CGST/SGST (each half rounded) or IGST by place of supply, cess, bill of supply / non-REGULAR suppliers untaxed, round-off to the rupee, deductions (retention, TDS s.194C rounded to the rupee, GST TDS s.51, advance recovery capped). Tests: worked examples incl. the API doc RA bill (net ₹3,23,680), half-up vs banker's cases, ~800 Hypothesis cases, engine output issued through the DB trigger. Mutation-checked (banker's rounding fails 4 tests). 280 tests
- [x] Phase 1.5: draft documents — `GET/POST /documents` (filters doc_type, status, book, party, project, date ranges, payment_state, q; idempotent create), `GET/PATCH/DELETE /documents/{id}` (drafts only, `lines` replaces all, recompute on every save, If-Match), `POST /documents:preview-totals`. Server derives registration, place of supply (site state), supply type, all amounts and project deductions (advance recovery capped at the outstanding advance); catalog/BOQ lines fill defaults. Schema: `documents.round_to_rupee` (+ column grant). Hypothesis found an edge case: a sub-rupee bill rounded to ₹0 with retention is refused (`deductions_exceed_total`), now pinned by a test. 305 tests
- [x] Phase 1.6: document lifecycle — `issue` (recompute, series row lock, gapless number, snapshots; idempotent + If-Match), `cancel`, `accept` / `decline`, `convert` (with `source_document_id`), `credit-notes` / `debit-notes` (copied lines, can't change type, credit total ≤ invoice). Tests incl. 4 parallel issues → INV/0001–0004 (mutation: without the series lock it fails 3/3), retries don't consume numbers, failed issues leave no gap, snapshots frozen; all 7 routes in the cross-tenant registry. 326 tests
- [x] Phase 1.7: PDFs and storage (owner decisions: WeasyPrint, worker in Docker) — HTML template with the CGST Rule 46 particulars, Indian digit grouping and amount in words (lakh/crore), auto-escaped; Celery task `render_document_pdf` queued on commit after issue, idempotent, stores to S3 (`apps/files/storage.py`; SeaweedFS locally) with an `attachments` row (size, SHA-256); `GET /documents/{id}/pdf` (302 to a 5-minute link / 202 while rendering / drafts on demand with DRAFT watermark). Backend `Dockerfile` (Python 3.14.8 slim, Pango, DejaVu fonts with ₹), compose profile `app` with `api` + `worker`; CI installs Pango and builds the image. Storage tests use moto. 352 tests
- [x] Phase 2.1: payments and allocations — `GET/POST /payments` (idempotent, optional allocations in the same request), `GET /payments/{id}` (allocated / unallocated), `POST /payments/{id}/allocations`, `DELETE /allocations/{id}`, `POST /payments/{id}/void` (If-Match, unwinds allocations). Service pre-checks give per-field codes; database rejections in races map to the same codes (threaded race test: one wins, the loser gets `allocation_exceeds_outstanding`). 369 tests
- [x] Phase 2.2: credit-note application — `GET/POST /documents/{id}/allocations` (an issued credit note settles invoices / debit notes of the same party, capped by its unapplied amount and their outstanding; unwind via `DELETE /allocations/{id}`); allocation code generalised to payment or credit-note sources with the same checks and race-safe error mapping. 376 tests
- [x] Phase 2.3: expenses — `GET/POST /expenses` (idempotent), `GET/PATCH /expenses/{id}` (If-Match, merged validation), `POST /expenses/{id}/void`; server-computed total and balance, payment status, vendor/project/attachment checks, filters incl. `payment_state`; site engineers record, viewers read. 388 tests
- [x] Phase 2.4: reports — `GET /reports/summary` (period vs previous period, books, outstanding now), `/reports/billing-by-month`, `/reports/receivables` (ageing buckets by party + totals), `/reports/projects` and `/reports/projects/{id}` (billing, deductions, outstanding, cost with non-claimable GST, margin), `/reports/gst-summary?period=YYYY-MM` (B2B/B2C by rate). SQL over the security_invoker views with an explicit tenant filter as well; one scenario with hand-computed numbers for every report, ageing tests relative to today, roles, cross-tenant test (A's data visible to A, invisible to B, A's project 404 for B). 402 tests
- [x] Phase 3.1: BOQ import — `POST /projects/{id}/boq-items:import` (multipart CSV / XLSX, `dry_run` preview, all or nothing). Header found below title rows, columns matched by name with aliases, heading / subtotal rows skipped, `₹` / `%` / Indian grouping commas accepted, each row validated like a single item, codes unique in the file and new to the project (no overwrite), errors as `rows[<spreadsheet row>].<field>`. File type from content; 5 MB / 5,000 rows; XLSX through defusedxml with an uncompressed-size check (zip bombs). Idempotency now hashes uploaded files by content. New dependencies: openpyxl, defusedxml. 418 tests
- [x] Phase 3.2: RA bills — `is_ra_bill` on invoices / bills of supply / proformas of a project; every line bills a BOQ item once; `ra_sequence` per project and type given at draft creation under a project row lock (one open RA draft, cancelled latest number reused); lines store this-bill quantity + `prev_cumulative_qty` snapshot (retaken at issue), API adds `up_to_date_qty`; BOQ cap for all billing documents unless the item is a variation, re-checked at issue with BOQ rows locked (parallel-issue test, mutation-checked: without the lock it fails 3/3); RA proforma → RA invoice on convert, notes never RA; contract quantity cannot drop below billed; `GET /projects/{id}/boq-progress`; PDF "RA Bill No. N" with previous / this bill / up to date columns; `is_ra_bill` list filter. No schema change (columns existed). 435 tests

## In progress

- Nothing. Next up: Phase 3.3, retention release.

## Next

Phase 0 — Foundations, in order:

1. ~~`docker-compose.yml` + `.env.example`~~ (done)
2. ~~Django project skeleton~~ (done)
3. ~~Database roles and migrations mirroring `db/schema.sql`~~ (done)
4. ~~Tenant context middleware + `tenant_context()`~~ (done)
5. ~~Auth~~ (done; see deferred items below)
6. ~~Memberships and role permissions~~ (done)
7. ~~Port `db/tests` to pytest + concurrency tests~~ (done)
8. ~~GitHub Actions CI~~ (done)

Phase 1 — core billing:

1. ~~API building blocks~~ (done)
2. ~~Business profile, GST registrations, number series~~ (done)
3. ~~Parties, projects, BOQ items, catalog~~ (done)
4. ~~Tax engine~~ (done)
5. ~~Draft documents~~ (done)
6. ~~Issue / cancel / accept / decline / convert, notes~~ (done)
7. ~~PDF generation and file storage~~ (done)
Phase 2 — money:

1. ~~Payments and allocations~~ (done)
2. ~~Credit-note allocation~~ (done)
3. ~~Expenses~~ (done)
4. ~~Reports~~ (done)

Phase 3 — construction (architecture §9). Already in place from Phases 1–2: BOQ items,
retention / TDS / GST-TDS / advance-recovery deductions on bills, project report.

1. ~~BOQ import (CSV/XLSX)~~ (done)
2. ~~RA bills~~ (done)
3. Retention release
4. TDS certificate reconciliation

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
- Tests needing real COMMITs use the `committed_db` fixture (no TRUNCATE flush; fresh tenant ids per test; the test DB is dropped at session end).
- **Auth items deferred** (need email sending, Redis or a schema decision): email verification (`verify-email`; architecture says it gates issuing documents), password forgot/reset, `PATCH /me`, Redis rate limits (login per IP, API per user, `RateLimit-*` headers), `Idempotency-Key` on signup (`idempotency_keys` requires a tenant and user, which do not exist yet at signup), HaveIBeenPwned check (Django's common-password list is used for now), sliding vs absolute session lifetime (sliding 30 days now).
- Invitations work only for people who already have an account (`422 no_account` otherwise, which tells an OWNER/ADMIN whether an email is registered). Email invitation links for new people come with email sending.
- Signup reveals whether an email is registered (`422 email_taken`); login and reset do not. Revisit with email verification (send a "you already have an account" email instead).
- Issuing does not yet require a verified email (architecture §2 / API §2): comes with email sending.
- Documents: cess is not exposed on lines yet (no stored cess rate); a document with a project must bill the project's client.
- Tax engine: reverse-charge documents and real invoices checked by a CA are still to do; the GST-TDS ₹2.5 lakh contract threshold is left to the caller (project flag).
- Expired idempotency keys are reused on demand; a periodic purge needs Celery beat (not set up yet).
- A PDF rendered before a document is cancelled still shows it as issued; re-render on cancel is not done yet.
- Expenses have no void reason column; the audit trail records who voided and when.
- Uploads by users (attachments API, presigned PUT, malware scan) are not built yet; only system-generated PDFs.
- `auth_sessions` has a `tenant_id` column but no RLS, by design (global table, read only by id / token hash).
- The app role has no privileges on `django_migrations`. `TransactionTestCase`-style flushes (TRUNCATE) will not work as the app role; concurrency tests in step 7 need their own setup/cleanup.
- Until JWT lands (step 5), unauthenticated API calls get 403 `permission_denied`; step 5 makes them 401.
- Compose publishes Postgres on host port **5433** and Redis on **6380**, because native PostgreSQL 17 and Redis Windows services already use 5432 / 6379 on the dev machine.

- Payables (vendor bills, payments to subcontractors) are deferred; expenses track their own payment for now.
- RA bills: credit notes do not reduce the billed quantity (a note may correct a rate rather than a quantity), so over-billing corrected by a credit note still counts against the BOQ; revisit with a quantity flag on note lines. The real-PDF render of the new RA columns is checked only as HTML on Windows (the WeasyPrint test runs in CI / Docker).
- BOQ import only adds items; updating existing items from a file (e.g. revised rates) is not supported. In a dry run, previewed items have null `id` / timestamps although the schema marks them as strings.
- Report exports (`POST /exports`: CSV / XLSX / GSTR-1 JSON) are not built yet (Phase 5 for GSTR-1).
- Reports run live SQL per request; fine at current scale, revisit (materialised summaries or caching) if dashboards get slow.
