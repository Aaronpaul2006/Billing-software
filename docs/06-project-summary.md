# SiteLedger: what has been built so far

*Summary as of 5 November 2026. Repository: https://github.com/Aaronpaul2006/Billing-software
(branch `main`). Step-by-step detail is in [`PROGRESS.md`](../PROGRESS.md); the API
reference is [`docs/02-api-design.md`](02-api-design.md).*

---

## 1. The product in one paragraph

**SiteLedger** (a placeholder name, to be replaced) is billing software for
construction companies and contractors in India. A business keeps its clients,
projects, bills of quantities (BOQ) and items; makes quotations, tax invoices,
running-account (RA) bills, credit and debit notes with correct GST; prints and
sends them; records payments, retention and TDS; and sees what is owed and what
each project earns. Many businesses share one installation, and each one only
ever sees its own data. The same software has a simple **client portal** where a
business's clients see their own bills, accept quotations and download PDFs.

## 2. Technology, in short

| Part | What it uses |
|---|---|
| Backend (API) | Python 3.14, Django 5.2 LTS, Django REST Framework, OpenAPI documentation |
| Database | PostgreSQL 17, with row-level security (each business sees only its own rows) |
| Background jobs | Celery workers with Redis (PDFs, emails, exports, reminders, file checks) |
| PDFs | WeasyPrint (HTML to PDF), with the GST invoice particulars of CGST rule 46 |
| File storage | S3-compatible storage (SeaweedFS on this PC, AWS S3 / Cloudflare R2 in production) |
| Web app | React 19, TypeScript, Vite, Tailwind, TanStack Query |
| Mobile app | Expo / React Native (built to M.3, then **stopped** by the owner on 3 Nov 2026) |
| Production | One server with Docker Compose, Caddy (automatic HTTPS), daily encrypted backups |

### Rules followed throughout (from `CLAUDE.md`)

- **Each business's data is separate**: the database itself enforces it (RLS forced on
  every business table, composite foreign keys), and another business's record always
  answers "not found" (404). Every API route is listed in a cross-business security test.
- **Money is exact**: always decimal (never floating point), rounded half up to the
  paisa, sent as text in the API, formatted with Indian grouping (₹3,41,020.00).
- **Issued documents never change**: corrections are credit / debit notes, or a
  cancellation with a reason; numbers have no gaps.
- **Safe edits**: version checks (If-Match) on every edit, so two people cannot
  overwrite each other; "Idempotency-Key" on every request that moves money, so a
  double-click never makes two bills or payments.
- **Audit trail**: every change to business data is recorded by the database.
- No secrets in the repository; the database schema file (`db/schema.sql`) and the
  migrations are kept in step and tested against each other.

---

## 3. Foundations (Phases 0 and 1, 19–20 Oct 2026)

- Concept review of the original idea, then the design: multi-business data model
  (`db/schema.sql`), architecture (`docs/01-architecture.md`), API design
  (`docs/02-api-design.md`), and project rules (`CLAUDE.md`).
- Local services in Docker: Postgres, Redis, SeaweedFS (file storage), Mailpit (catches
  emails).
- Database roles: the API runs as a role that can never bypass the data separation.
- Sign-in: sign-up, login, 2-step sign-in (authenticator app or emailed code, recovery
  codes), sessions, password reset, email confirmation, lockout after failed attempts,
  rate limits.
- Team: roles (owner, admin, accountant, site engineer, viewer), invitations, a
  permission matrix tested cell by cell.
- Business settings: GST registrations (GSTIN check digit, state rules), number series
  per document type and financial year.
- Masters: clients and vendors (GST treatment rules), projects (site state decides the
  place of supply), catalog items, BOQ.
- **Tax engine**: CGST + SGST or IGST by place of supply, cess, bills of supply, round-off;
  pure, exact and heavily tested.
- **Documents**: drafts, issue (gapless numbers, frozen copies of supplier and client
  details), cancel, quotation accept / decline, convert, credit and debit notes, PDFs.
- Automated checks on every push (GitHub Actions): lint, types, tests, schema sync.

## 4. Money and construction features (Phases 2 and 3)

- **Payments** with allocation to bills ("fill oldest first"), voiding, credit notes
  applied to bills.
- **Expenses** per project or office, with input tax credit, part payments and receipts.
- **Reports**: billing summary, billing by month, receivables with ageing, project
  margins.
- **BOQ import** from Excel / CSV; **RA bills** that bill BOQ quantities with previous /
  this bill / up-to-date columns.
- **Retention** deducted on bills and **released** later; **income-tax TDS** (s.194C) and
  **GST TDS** (s.51) deductions; **mobilisation advance** recovery.
- **TDS certificate reconciliation** (Form 16A against what was deducted).

## 5. The web app (W.1–W.7, then launch gaps, exports, production)

- Web app: sign-in with 2-step, dashboard, clients, projects with BOQ / retention / TDS
  tabs, the bill editor, payments, expenses, reports, settings.
- **Launch gaps**: emails through a background job; rate limits; file uploads straight to
  storage with type / size checks and virus scanning (ClamAV); housekeeping jobs.
- **Exports**: invoice register, payments, expenses, receivables, BOQ progress, project
  margins (CSV / Excel), and **GSTR-1 JSON** for the GST offline tool.
- **Production setup** (P.1–P.3): the production Docker stack with HTTPS and security
  headers, daily encrypted off-site backups with a tested restore, deploy workflow and an
  operations runbook (`docs/03-operations.md`).
- **GST correctness**: SEZ and export supplies, LUT, reverse charge, the declarations
  each such invoice must carry.
- **Your account**: profile, email change, password change, sessions, 2-step settings;
  **invitations by email** for people without an account.
- **Mobile app M.1–M.3** (owner app: dashboard, bills, payments, record a payment, share
  PDFs). **Stopped by the owner on 3 Nov 2026**: web first. The mobile code stays and
  still compiles against the API.

## 6. Additions from 1 Nov 2026 (statement, reminders, portal and more)

| Step | What it added |
|---|---|
| W.1 | **Statement of account** for a client (opening balance, every bill / payment / note with a running balance), as CSV, Excel or PDF |
| W.2 | **Payment reminders** by email: automatic (3 days before the due date, on it, then 7 / 15 / 30 days late) and "send one now" |
| W.3 | **Quotation / bill templates** ("2BHK interior package") to start new drafts |
| W.4 | **Material variants** (e.g. cement brand) with their own rate |
| W.5 | **Client portal**: clients sign in to see their bills, payments and statement, download PDFs and accept / decline quotations |
| W.6 | **Main dashboard**: billed, collected, outstanding, overdue, expenses and margin; a 12-month chart; overdue bills with "Send reminder"; projects losing money |
| W.7 | **Speed check** with a large business (11,000 bills, 8,000 payments): slow pages fixed (one page went from 108 database queries to 8) |
| H.1 | **Public home page**: features, how it works, contact (phone / WhatsApp +91 73560 60464, aaronpaulsanthosh@gmail.com), FAQ |
| H.2 | **First page after sign-in**: greeting, quick actions, and a "Set up your business" checklist |

---

## 7. "Billing made complete and easy" (the owner's brief of 3 Nov 2026)

Goal: billing as complete as Tally, but simpler for an office worker. Step B.0 was a
gap report and list of ideas (`docs/04-billing-ideas.md`); the owner approved the
recommendations: drafts save on the server, everyone who can see a bill sees its
history, WhatsApp opens a message and staff attach the PDF, site engineers do not add
items or clients, the copy label is chosen when printing.

### Making bills faster

| Step | What you get |
|---|---|
| **B.1** Item search and quick add | Search items as you type (name, description, variant, HSN); recently used first; add a **new item or client in a popup** without leaving the bill |
| **B.2** Item import | Add the whole catalog from Excel / CSV: download a sample, check, preview row errors in plain words, import |
| **B.3** Client import | The same for clients (GSTIN, GST type, state, PAN, contact, credit days) |
| **B.4** Keyboard-first bill screen | Like Tally: **Enter** moves to the next box (and adds a line at the end), **Alt+N** adds a line, **Ctrl+S** saves, **Ctrl+Enter** saves and opens the final review, **Esc** goes back; move / insert / remove lines; the client's balance shows when chosen |
| **B.5** Discount %, bulk edit, payment terms | Discount as ₹ or %; change rate / discount / GST of many lines at once; a client's **credit days** set the due date |
| **B.6** Autosave | A draft saves itself two seconds after typing stops ("Saved at 10:42"); nothing is lost on a closed tab |
| **B.7** Lines from Excel | Import bill lines from a file, or **paste cells copied from Excel** straight into the bill |
| **B.8** Last rate | "Last charged to this client: ₹395.00 on INV/0012" with a one-click "Use" |
| **B.9** Measurement sheets | Nos × length × breadth × height rows per line, with deductions (door openings); the line quantity is their total; rows print on the PDF |
| **B.10** Duplicate, convert, Alter | **Duplicate** any bill; **Make tax invoice** from a quotation in one click; **Alter…** explains in plain words how to change an issued bill (credit note, debit note, or cancel and make a corrected copy) |

### Checking, printing and sending

| Step | What you get |
|---|---|
| **B.11** Change history | At the bottom of every bill: who did what and when, in plain words ("Issued as INV/0001", "Line 1: rate ₹6,800.00 → ₹6,800.10", "Payment received", "Emailed to …"); autosaves grouped into one entry |
| **B.12** Bill printing settings | **Settings → Bill printing**: logo, signature, bank details (IFSC and account number checked), UPI ID, default terms (filled into every new bill), simple or detailed layout |
| **B.13** The complete PDF | Logo; GSTIN; client and place of supply; **HSN summary**; tax breakup; deductions; amount in words; **bank details and a UPI QR code for the exact amount** (`upi://pay?…&tn=<bill number>`); terms; signature; page numbers; measurement rows; **Original / Duplicate / Triplicate** label chosen at print (CGST rule 48). A bill keeps the settings it was issued with |
| **B.14** Final review before issuing | "Issue…" (or Ctrl+Enter) shows a summary and **warnings, never a block**: no number series, client without GSTIN (stronger when their PAN shows a business), possible duplicate bill (same client, total within 1 %, last 7 days), no due date, missing HSN, a rate far below the usual one; each with a link to fix it |
| **B.15** Print, download, email, WhatsApp | On issued bills: **Print**, **Download**, **Email…** (the PDF attached, bank / UPI details in the email, replies come to the sender; recorded in the history), **WhatsApp** (downloads the PDF and opens a ready message to the client's number) |
| **B.16** Tally export | **Exports → Tally**: sales, credit and debit notes and receipts for a date range as a Tally XML file (balanced vouchers, bill-wise references); ledger names in **Settings → Tally export**; the export lists the ledgers to create in Tally first |

Every step: a short plan first, then the code, backend and web tests, documentation, an
update of `PROGRESS.md`, a commit and a push, only with all checks green.

---

## 8. Demo and a reliable setup on this PC (4–5 Nov 2026)

- **Demo business** filled with sample data through the real API ("Demo Constructions",
  Kochi): GSTIN and number series, 4 clients (one in Karnataka, so IGST), 3 projects
  with retention and TDS, 7 items, bill printing with a logo, INV/0001 paid,
  INV/0002 part paid with a measurement sheet, INV/0003 with credit note CN/0001, an
  accepted quotation turned into a draft, and a draft whose review shows warnings.
  `backend/scripts/seed_demo.py` does all of it again for any email (it signs the
  account up if needed). The demo account's password, authenticator key and recovery
  codes were given in the conversation and are **not** stored in the repository.
- **Guide**: [`docs/05-demo.md`](05-demo.md): starting and stopping, filling the demo,
  and things to try.
- **Reliability** (the web server and Docker kept being stopped for low memory):
  - everything now runs in Docker and comes back by itself after a restart; the web
    app is served by a 24 MB Caddy container instead of a development server;
  - **one-click start / stop**: `scripts\demo-up.cmd` (starts Docker, keeps the other
    project PrintPulse off, rebuilds the web app when it changed, starts, updates the
    database, opens the browser) and `scripts\demo-down.cmd`;
  - Docker's memory is capped at 4 GB (`%USERPROFILE%\.wslconfig`), so other apps
    always have room; the demo itself uses about 0.7 GB.
- **A production fix found on the way**: the live site's security policy would have
  blocked the logo preview and the Print button; fixed in `deploy/Caddyfile`, and the
  local demo now uses the same policy so such problems show up early.

---

## 9. Where things stand

| Check | Result (5 Nov 2026) |
|---|---|
| Backend tests | **743 passed** (3 skipped: the opt-in speed check, and two real-PDF checks that run in Docker, where WeasyPrint works) |
| Web tests | **214 passed** |
| Mobile tests | 61 passed (kept green; development stopped) |
| Database rule checks (PGlite) | 32 passed |
| Lint, type checks, formatting, schema sync | all clean |
| Commits on `main` | 92 since 19 Oct 2026 (including this summary) |

**How to see it:** double-click `scripts\demo-up.cmd`, then open http://localhost:5173.
Emails the demo sends are in Mailpit, http://127.0.0.1:8025.

---

## 10. Open items and decisions for the owner

1. **Try a Tally import** with a short period into a test company (create the listed
   ledgers first; manual voucher numbering). It could not be tested here: no Tally on
   this PC, and Tally's own published samples contain mistakes.
2. **The product name**: "SiteLedger" is a placeholder (`web/src/brand.ts`); once the
   real name is chosen, the home page's `noindex` comes off.
3. **Hosting**: putting it on a small cloud server (the production setup is ready in
   `deploy/`) makes it always on and reachable from a phone; it needs a monthly fee and
   a domain name.
4. **Proposed**: a "Make new recovery codes" button under Account → Security (today
   codes can only be refreshed by turning 2-step sign-in off and on).
5. **Before relying on GST files**: check a real month's GSTR-1 export and some real
   invoices with a CA.
6. Known limits are listed in `PROGRESS.md` (Known gaps), for example: payables to
   vendors and subcontractors are not built yet; the mobile app is paused; client ledger
   masters are not in the Tally file.
