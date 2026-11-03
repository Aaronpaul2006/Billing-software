# API Design

Status: design · Last updated: 2026-10-19

One REST API serves the web app and the owner's mobile app. The machine-readable
OpenAPI 3.1 spec is **generated from code** (drf-spectacular) and published at
`/api/v1/schema/`; this document defines the conventions and the endpoint
surface that the code must follow.

---

## 1. Conventions

### Base & versioning
* Base URL: `https://api.<domain>/api/v1`
* Breaking changes go to `/api/v2`; additive changes (new fields, endpoints)
  don't need a new version. Clients must ignore unknown fields.

### Tenant
* The tenant is **not** in the URL or a header. It is the `tid` claim of the
  access token, chosen at login or via `POST /auth/switch-tenant`. A client
  therefore cannot address another tenant even by mistake.

### Format
* JSON, `snake_case`, UTF-8.
* **Money and quantities are strings**: `"amount": "11800.00"`,
  `"quantity": "12.500"`. JSON numbers become binary floats in JavaScript and
  Dart and corrupt amounts. Requests with numeric JSON for money fields are
  rejected.
* Dates are `YYYY-MM-DD`; timestamps are ISO 8601 UTC (`2026-10-19T08:30:00Z`).
  Display timezone comes from the tenant setting.
* Ids are UUID strings. Enums are UPPER_SNAKE strings.

### Pagination (cursor based)
```
GET /documents?limit=50&cursor=eyJk...
200 { "results": [...], "next_cursor": "eyJk..." | null }
```
`limit` defaults to 25, max 100. Cursors are opaque and stable under inserts
(unlike page numbers). Default order: newest first (by UUIDv7 id).

### Filtering & sorting
* Exact filters as query params: `?status=ISSUED&doc_type=TAX_INVOICE`.
* Multi-value: `?doc_type=TAX_INVOICE,DEBIT_NOTE`.
* Ranges: `?doc_date_from=2026-04-01&doc_date_to=2027-03-31`.
* Search: `?q=villa` (trigram search on names / numbers).
* Sorting: `?ordering=-doc_date` (only allow-listed fields).

### Errors: RFC 9457 `application/problem+json`
```json
{
  "type": "https://docs.<domain>/errors/validation",
  "title": "Validation failed",
  "status": 422,
  "code": "validation_error",
  "detail": "2 fields are invalid.",
  "errors": [
    { "field": "lines[0].rate", "code": "max_decimal_places", "message": "At most 2 decimal places." },
    { "field": "party_id", "code": "not_found", "message": "Party does not exist." }
  ],
  "request_id": "01JAB3..."
}
```

| Status | When |
|---|---|
| 400 | Malformed JSON / bad query parameter |
| 401 | Missing / expired / invalid token |
| 403 | Authenticated, but the role lacks the permission |
| 404 | Not found **or belongs to another tenant** (never 403, to avoid revealing that it exists) |
| 409 | State conflict: issuing a non-draft, cancelling a settled invoice, duplicate code |
| 412 | `If-Match` version is stale (someone else saved first) |
| 422 | Validation errors |
| 428 | `If-Match` or `Idempotency-Key` required but missing |
| 429 | Rate limited (`Retry-After` header) |

Database rule violations (triggers / CHECKs) are mapped to 409/422 with a
stable `code`. Raw database messages are never returned.

### Concurrency: optimistic locking
* Editable resources return `version` and an `ETag: "v7"` header.
* `PATCH` / `PUT` / state-changing `POST`s on a specific resource **require**
  `If-Match: "v7"`. A mismatch gives 412 with the current resource in the body
  so the client can show "this was changed by Priya, reload?".
  Codes: `428 if_match_required`, `412 stale_version` (body has `current`).

### Idempotency
* Required on: `POST /documents`, `/documents/{id}/issue`, `/payments`,
  `/expenses`, `/documents/{id}/credit-notes`, signup (and every other money or
  document action marked so in the schema).
* Honoured when sent (optional) on master-data creates: `POST /parties`,
  `/projects`, `/projects/{id}/boq-items`, `/catalog-items`,
  `/gst-registrations`, `/document-series`. The web app always sends one, so a
  retried create cannot make a duplicate.
* Header `Idempotency-Key: <uuid>`, generated once per user action by the client
  and reused on retries.
* Same key + same body → the original response is replayed (with
  `Idempotent-Replayed: true`). Same key + different body → 422. Keys expire
  after 24 h; an hourly job (Celery beat) deletes expired keys.
  Codes: `428 idempotency_key_required`, `422 idempotency_key_reused`. A request
  that fails stores nothing, so its retry runs again.

### Rate limits
Response headers `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`
(seconds until the window ends) on every response that counted against a
limit; when several did, the headers describe the one closest to its limit.
Over a limit: `429 rate_limited`, a `detail` that says how long to wait,
`retry_after` (seconds) in the body and a `Retry-After` header.

Built in L.2 (2026-10-21). Fixed-window counters in Redis (window starts at
the first request), limits in settings `RATE_LIMITS`:

| Rule | Limit | Counted per |
|---|---|---|
| `POST /auth/login` | 20 / min · 5 / min | client IP · email |
| `POST /auth/mfa/verify` | 20 / min | client IP |
| `POST /auth/signup` | 10 / hour | client IP |
| `POST /auth/password/forgot` | 20 / hour · 3 / hour | client IP · email |
| `POST /auth/password/reset` | 20 / hour | client IP |
| `POST /auth/verify-email/resend` | 3 / hour | user |
| Every request with a valid access token | 600 / min | user |

Emails are hashed before they become Redis keys. The client IP is the
connection's address, or with `TRUSTED_PROXY_COUNT = n` the address the
outermost of n trusted proxies added to `X-Forwarded-For`. If Redis is
unreachable, requests are allowed and a warning is logged (the database
lockout still guards passwords).

---

## 2. Authentication

| Method & path | Purpose |
|---|---|
| `POST /auth/signup` | Create user + first tenant (the user becomes OWNER). Email verification required before issuing documents. |
| `POST /auth/verify-email` | `{token}` from the emailed link → `204`. No sign-in needed. |
| `POST /auth/verify-email/resend` | Signed in: email a new link (no-op once verified) → `204` |
| `POST /auth/login` | `{email, password}` → either `{mfa_required: true, mfa_token, mfa_method}` or `{tenants: [...], ...tokens}` |
| `POST /auth/mfa/verify` | `{mfa_token, code}` → tokens (`code`: from the authenticator app, or the emailed one when `mfa_method` is `email`) |
| `POST /auth/token/refresh` | Rotates the refresh token (cookie for web, body for mobile) → new access + refresh |
| `POST /auth/switch-tenant` | `{tenant_id}` → new tokens scoped to that tenant (membership checked) |
| `POST /auth/logout` | Revoke the current session |
| `GET /auth/sessions` · `DELETE /auth/sessions/{id}` | List / revoke your devices |
| `POST /auth/password/forgot` | `{email}` → always `204` (no account enumeration) |
| `POST /auth/password/reset` | `{token, password}` → `204`; signs out every session |
| `POST /auth/mfa/setup` · `POST /auth/mfa/enable` · `POST /auth/mfa/disable` | TOTP enrolment (disable requires password + code) |
| `GET /me` · `PATCH /me` | Profile (`full_name`, `phone`), memberships |
| `POST /me/email` · `POST /auth/email/confirm` | Change the sign-in email: `{new_email, password}` → a link to the new address; `{token}` from it switches (K.1) |
| `POST /auth/password/change` | `{current_password, new_password}` while signed in; other devices signed out (K.1) |

Access token claims: `sub` (user), `tid` (tenant), `role`, `sid` (session
family), `amr` (`["pwd"]`, `["otp","pwd"]` or `["email","pwd"]`), `iss`,
`iat`, `exp` (10 min), `typ`; `pid` (the client) for role CLIENT and only
then. HS256 only, `kid` in the header for key rotation.

**Client-portal sign-in (W.5a, 2026-11-02).** Someone with an active CLIENT
membership and no authenticator app gets `mfa_method: "email"` from login: a
6-digit code is emailed (10 minutes, one use, 5 tries; a new login sends a
new one and the old stops working) and goes to `/auth/mfa/verify` as `code`
→ tokens with `amr ["email","pwd"]`. Wrong codes count towards the login
lockout. Users with TOTP keep `mfa_method: "totp"`. A CLIENT token without
`otp` or `email` gets `403 mfa_enrollment_required`. Sessions keep their
`amr` across refreshes (stored on the session).

Implemented (Phase 0.5) as of 2026-10-19:

* **`client`**: login, signup, MFA verify, switch-tenant and MFA enable take
  `client: "web" | "mobile"` (default `mobile`). Mobile gets `refresh_token`
  in the body; web gets it only as an `HttpOnly; SameSite=Strict` cookie on
  path `/api/v1/auth`, and `POST /auth/token/refresh` with an empty body uses
  the cookie.
* **Sessions** are refresh-token families; `sid` is the family id. Every
  request checks the family is live, so logout and `DELETE /auth/sessions/{id}`
  take effect immediately. Reusing a rotated refresh token revokes the family
  (`401 refresh_token_reused`); two concurrent refreshes with one token count
  as reuse, so clients must serialise refreshes.
* **MFA gate**: an OWNER/ADMIN whose token lacks `otp` gets
  `403 mfa_enrollment_required` everywhere except `/me`, `/auth/mfa/setup`,
  `/auth/mfa/enable`, `/auth/sessions*`, `/auth/switch-tenant` and
  `/auth/logout`. Token responses carry `mfa_enrollment_required`. Enabling MFA
  returns 10 one-time `recovery_codes` and new tokens, and signs out every
  other session. OWNER/ADMIN cannot disable MFA (`409 mfa_required_for_role`).
* **Error codes**: `401 invalid_credentials` (wrong password, unknown email and
  locked account look identical), `invalid_mfa_code`, `invalid_mfa_token`,
  `invalid_refresh_token`, `refresh_token_reused`, `token_expired`,
  `invalid_token`, `session_revoked`; `403 no_active_membership`;
  `422 weak_password` / `email_taken` (field errors).
* **Email verification & password reset** (L.1, 2026-10-21): signup emails a
  verification link; `GET /me` has `email_verified`; issuing a document needs
  a verified address (`403 email_not_verified`). Links point at the web app
  (`APP_BASE_URL/verify-email?token=…`, `/reset-password?token=…`) and carry
  signed, expiring tokens, not database rows: verification lasts 7 days and
  names the address it confirms; a reset link lasts 1 hour and holds a keyed
  fingerprint of the current password hash, so it works once. A reset clears
  a failed-login lock, confirms the email, signs out every session and sends a
  "password changed" notice; MFA still applies at the next login. A bad link
  is `422` with field `token`: `link_expired` or `link_invalid`. Emails are
  sent by a Celery task after commit (Mailpit in dev); the task builds the
  token, so tokens never sit in the queue.
* **Your account** (K.1, 2026-10-22): `PATCH /me` (name; phone stored as `+`
  and 10–15 digits, spaces / dashes / brackets dropped). Password change:
  `422 invalid_password` on `current_password` (counts towards the lockout),
  `weak_password` on `new_password`; other sessions revoked, notice emailed;
  5 per hour. Email change: `422 invalid_password` (field `password`),
  `same_email`, `email_taken` on `new_email`; the link (1 day) names the
  address it moves from, so it stops working if the email changed meanwhile
  (`link_invalid`); confirming marks the new address verified and emails the
  old one; opening it twice is harmless; 3 per hour.
* Not yet built: `Idempotency-Key` on signup (see PROGRESS.md).

---

## 3. Tenant administration (OWNER / ADMIN)

| Method & path | Purpose |
|---|---|
| `GET /tenant` · `PATCH /tenant` | Current business profile (`legal_name`, `trade_name`, `pan`, `timezone`); PATCH needs `If-Match`. A PAN that differs from the business's GSTINs → `422 pan_mismatch` |
| `GET/POST /members` · `PATCH/DELETE /members/{id}` | Invite by email, change role, revoke. `POST {email, role}` invites an existing account (status INVITED; `422 no_account`, `409 already_member` / `already_invited`; a removed member can be invited again). `PATCH {role}`, `DELETE` (→ REVOKED, idempotent). Errors: `403 permission_denied`, `owner_protected`, `cannot_modify_self`; `409 last_owner`, `member_revoked`; `404` for other tenants' members |
| `GET /invitations` · `POST /invitations/{id}/accept` · `POST /invitations/{id}/decline` | Any signed-in user: their own pending invitations (business name, role, inviter). Accept → ACTIVE (then `switch-tenant`); decline → REVOKED. Someone else's or an already answered invitation → `404` |
| `GET/POST /email-invitations` · `DELETE /email-invitations/{id}` · `POST /email-invitations/{id}/resend` | People with no account yet (K.2): `POST {email, role}` emails a signed link to `/join` (7 days). `422 has_account` (invite them as a member instead), `409 already_invited`, `403 owner_protected` (an ADMIN inviting an OWNER); 30 per hour. The list shows pending ones with `expired`; resend renews the 7 days; withdraw → REVOKED (`409 not_pending` once answered) |
| `GET /auth/join?token=` · `POST /auth/join` | Public, from the email: the invitation (email, company, role, inviter); `{token, full_name, password, client}` creates the account (email confirmed: the link proves the inbox), joins with the invited role (ACTIVE) and signs in (`201` tokens). `422 link_invalid` / `link_expired`, `weak_password`, `409 account_exists`. Someone who signs up the normal way instead finds their pending email invitations as INVITED memberships (database function `claim_email_invitations()`) |
| `GET /tenant/setup` | The setup checklist on the first page after sign-in (H.2): `gst_registration`, `number_series`, `client`, `project`, `first_bill` (anything issued), `team` (another member, or invited; portal users do not count), `complete`. Any member (`tenant.read`) |
| `GET/POST /parties/{id}/portal-users` · `DELETE /parties/{id}/portal-users/{portal_user_id}` | Client portal (W.5a): who may sign in to see this client's bills, payments and BOQ progress. `POST {email}`: an account holder gets an INVITED CLIENT membership (`kind: MEMBER`, accepted from `/invitations`); anyone else an email invitation to `/join` (`kind: EMAIL_INVITATION`, 7 days, resend / withdraw also via `/email-invitations/{id}`). `409 already_member` (staff of this business), `other_client` (portal user of another client), `already_invited`; `422 not_a_client` (a vendor-only party), `account_inactive`; 30 per hour. The list shows ACTIVE / INVITED members and PENDING email invitations. `DELETE` → REVOKED and signs them out at once (idempotent; `404` unknown). OWNER / ADMIN; another tenant's party `404`. Portal users never appear in `/members` (`404` there) or `/email-invitations`, and `CLIENT` is not a role `/members` accepts |
| `GET/POST /gst-registrations` · `GET/PATCH /gst-registrations/{id}` | Our GSTINs. GSTIN validated incl. check digit (`invalid_gstin`), state taken from it, address must be in that state, GSTIN must carry the business PAN (`pan_mismatch`), unique (`gstin_taken`). GSTIN / type / state cannot change. Exactly one default (`409 default_required`) |
| `GET/POST /document-series` · `GET/PATCH /document-series/{id}` | Number series per registration, doc type and FY (`?doc_type=A,B&gst_registration_id=&fy_start_year=&is_active=`). One active series per registration/type/year (`409 active_series_exists`). Once anything was issued, `prefix`, `pad_width` and `next_number` are locked (`409 series_in_use`). Non-REGULAR registrations cannot hold TAX_INVOICE / CREDIT_NOTE / DEBIT_NOTE series (`422 doc_type_not_allowed`). Responses include `next_doc_number` |
| `GET /audit-log?table=documents&row_id=...` | Change history (OWNER/ADMIN) |

---

## 4. Master data

| Method & path | Notes |
|---|---|
| `GET/POST /parties` · `GET/PATCH /parties/{id}` | `?is_customer=true&q=...`. GSTIN validated (format + checksum). Archive with `PATCH {is_active: false}`; no delete. |
| `GET/POST /projects` · `GET/PATCH /projects/{id}` | `?status=ACTIVE&client_party_id=...&q=`; responses carry `client_name` |
| `GET/POST /projects/{id}/boq-items` · `PATCH/DELETE /boq-items/{id}` | Bulk import: `POST /projects/{id}/boq-items:import` (CSV/XLSX, validated, all-or-nothing). Delete only if never billed; `contract_qty` cannot go below the quantity billed, nor `is_variation` be turned off once billed past it (`422 below_billed`). |
| `GET /projects/{id}/boq-progress` | Per BOQ item: contract vs billed quantity and value, balance, progress %; plus totals. All items, not paginated. |
| `GET/POST /catalog-items` · `PATCH/DELETE /catalog-items/{id}` | Reusable items and rates. Search (B.1): `?q=` (every word must match the name, description or a variant's value; or the start of the HSN/SAC), `is_active`, `sac_hsn`; `?used=true&ordering=-last_used_at` lists the items used most recently on a bill (`last_used_at` in each row) |

### BOQ import

`POST /projects/{id}/boq-items:import`, `multipart/form-data`: `file` (CSV in
UTF-8 or `.xlsx`; type detected from the content; at most 5 MB and 5,000 rows)
and `dry_run` (`true` validates and previews, saves nothing). Needs
`Idempotency-Key`; a replay must send the same file. Permission `boq.edit`.

- The header row may sit below title rows (first 20 rows searched). Columns are
  matched by name, case and punctuation ignored: `item_code` (Item No., Code),
  `description` (Particulars), `unit` (UOM), `contract_qty` (Qty, Quantity),
  `rate` (Unit Rate) are required; `gst_rate` (GST, GST %; default 18),
  `sac_hsn` (HSN/SAC), `is_variation` and `sort_order` are optional. Other
  columns (e.g. Amount) are ignored and listed in `ignored_columns`.
- Rows with no unit, quantity and rate are headings or subtotals: skipped and
  listed in `skipped_rows`. Numbers may carry `₹`, `%` and Indian grouping
  commas.
- All or nothing. Each row has the same rules as a single item; codes must be
  unique in the file and new to the project (`item_code_taken`,
  `duplicate_item_code`; no overwrite, since items may already be billed).
  Errors name spreadsheet rows: `{"field": "rows[7].rate", "code": "min_value"}`
  (first 100 rows with errors). File-level codes on `file`: `missing_columns`,
  `no_rows`, `not_utf8`, `unsupported_file`, `file_too_large`, `too_many_rows`.
- `201 {dry_run, count, skipped_rows, ignored_columns, items}` (dry run: `200`).
  Without `sort_order`, items are appended after the project's existing ones.

---

## 5. Billing documents

### Endpoints

| Method & path | Purpose | Permission |
|---|---|---|
| `GET /documents` | List with filters (below) | read |
| `POST /documents` | Create a **draft** with lines | drafts |
| `GET /documents/{id}` | Full document with lines, totals, settlements | read |
| `PATCH /documents/{id}` | Edit a draft; `lines` replaces all lines. Server recomputes totals. | drafts |
| `DELETE /documents/{id}` | Delete a draft | drafts |
| `POST /documents/{id}/issue` | Assign number, snapshot, lock | issue |
| `POST /documents/{id}/cancel` | `{reason}`; must have no settlements | issue |
| `POST /documents/{id}/accept` · `/decline` | Quotations only | issue |
| `POST /documents/{id}/convert` | `{to: "TAX_INVOICE"}` → new draft copied from a quotation/proforma | drafts |
| `POST /documents/{id}/credit-notes` · `/debit-notes` | New draft note referencing this invoice | drafts |
| `GET /documents/{id}/pdf` | 302 to a 5-minute presigned URL (rendered by the Celery worker after issue; `202` + `Retry-After` while it is being made; drafts are rendered on demand with a "DRAFT" watermark and never stored). `?as=link` answers `200 {url, expires_in}` instead of the 302, for browsers (a cross-origin redirect cannot be read) | read |
| `POST /documents/{id}/send` | Email the PDF to the party (queued) | issue |
| `POST /documents:preview-totals` | Run the tax engine on an unsaved payload (live totals while typing) | drafts |

Document responses carry `party_name` (frozen at issue, the current name on drafts) and `project_name`.

### List filters
`doc_type`, `status`, `book=GST|NON_GST|ALL` (maps to `is_gst_document`),
`party_id`, `project_id`, `is_ra_bill`, `doc_date_from/to`, `due_date_to`,
`payment_state=UNPAID|PARTIAL|PAID|OPEN` (`OPEN`: anything still owed), `q`.
List values are comma-separated (`doc_type=TAX_INVOICE,BILL_OF_SUPPLY`); `ordering`
takes several fields (`doc_date,doc_number`).

### Create a draft
```http
POST /api/v1/documents
Idempotency-Key: 6f1c2a1e-6c1f-4b8e-9d2a-0c7f3e5b9a10
```
```json
{
  "doc_type": "TAX_INVOICE",
  "gst_registration_id": "0192f5c4-...",
  "party_id": "0192f5c4-...",
  "project_id": "0192f5c4-...",
  "doc_date": "2026-10-19",
  "due_date": "2026-11-18",
  "is_ra_bill": true,
  "lines": [
    {
      "boq_item_id": "0192f5c4-...",
      "description": "RCC M25 for slab, 2nd floor",
      "sac_hsn": "9954",
      "unit": "cum",
      "quantity": "42.500",
      "rate": "6800.00",
      "gst_rate": "18.00"
    }
  ],
  "notes": "RA Bill 3 for work up to 15 Oct"
}
```
The client never sends tax amounts, totals, `place_of_supply` or
`supply_type`. The server derives them (place of supply from the project's
site state) and returns them.

Built in Phase 1.5: the registration is the project's (or the tenant default;
a different one → `422 registration_mismatch`); without a project the place of
supply is the party's state, else our own; with a project the party must be its
client (`party_mismatch`) and a customer (`not_a_customer`); lines may name a
`catalog_item_id` / `boq_item_id` and leave out description, unit, SAC/HSN,
rate and GST rate; `round_to_rupee` is stored with the draft; deductions come
from the project (invoices, bills of supply, proformas). `POST /documents`
accepts QUOTATION, PROFORMA, TAX_INVOICE and BILL_OF_SUPPLY; notes come from
their own endpoints (Phase 1.6), RA bills below (Phase 3.2). Example response:

```json
{
  "id": "0192f5d0-...",
  "version": 1,
  "doc_type": "TAX_INVOICE",
  "status": "DRAFT",
  "doc_number": null,
  "ra_sequence": 3,
  "place_of_supply": "32",
  "supply_type": "INTRA_STATE",
  "totals": {
    "subtotal": "289000.00",
    "cgst": "26010.00", "sgst": "26010.00", "igst": "0.00", "cess": "0.00",
    "round_off": "0.00",
    "grand_total": "341020.00",
    "retention": "14450.00",
    "income_tax_tds": "2890.00",
    "gst_tds": "0.00",
    "advance_recovery": "0.00",
    "net_receivable": "323680.00",
    "amount_settled": "0.00",
    "outstanding": "323680.00"
  },
  "lines": [ ... ]
}
```

### Catalog item variants (W.4)

A catalog item may have variants (`attribute` + `value`, e.g. Brand:
UltraTech) with a `rate_delta` (may be negative). `GET /catalog-items`
includes each item's `variants`. A draft line naming `catalog_item_id` and
`catalog_variant_id` gets, unless typed: rate = item rate + delta (`422
negative_rate` below zero), description "item — Brand: UltraTech", unit,
HSN / SAC and GST from the item. `422 variant_mismatch` (another item's
variant), `variant_without_item`. The database enforces the pairing too
(foreign key on tenant, item, variant).

| Method & path | |
|---|---|
| `GET/POST /catalog-items/{id}/variants` | List, add (`409 variant_exists`; `masters.edit`) |
| `GET/PATCH/DELETE /catalog-variants/{id}` | Read, edit (If-Match), delete only if no bill uses it (`409 variant_used`: archive with `is_active: false`) |

### Templates (W.3)

A template keeps a quote's or bill's lines (description, HSN / SAC, unit,
quantity, rate, GST %, discount, as typed: no catalog or BOQ link), notes,
terms and, for quotations, `valid_days`. Types: QUOTATION, PROFORMA,
TAX_INVOICE, BILL_OF_SUPPLY (not notes). Names are unique per tenant
(`409 template_name_taken`).

| Method & path | |
|---|---|
| `GET/POST /document-templates` · `GET/PATCH/DELETE /document-templates/{id}` | List (`?doc_type=`), create, read, edit (If-Match; turning a quotation template into another type drops `valid_days`), delete. Write: `masters.edit` |
| `POST /documents/{id}/save-as-template` | `{name, valid_days?}` → `201` template from the document (BOQ lines become plain lines; a quote's validity is kept as days); `409 not_templatable` (notes), `409 no_lines` |
| `POST /document-templates/{id}/use` | `{party_id, project_id?, doc_date?}` (Idempotency-Key; `documents.draft`) → `201` a new **draft** built by the normal draft rules (place of supply, GST, totals, references); a quotation's `valid_until` = `doc_date` + `valid_days` |

### SEZ, exports, LUT, reverse charge (G.1)

Documents carry `supply_category` (`REGULAR` / `SEZ` / `EXPORT`, derived:
SEZ from the client's GST treatment; EXPORT for an overseas client without a
project; an overseas client's works on an Indian site are `REGULAR`), `lut`
and `reverse_charge`; preview-totals returns them too.

* SEZ: always `INTER_STATE` / IGST, place of supply = site (or client) state.
  EXPORT: place of supply `96`.
* `lut` (write, optional, SEZ / export only): `true` = zero-rated without
  IGST under the registration's Letter of Undertaking (taxes 0, rates kept),
  `false` = charge IGST, omitted / `null` = under the LUT when the
  registration has one for the document's financial year. `422 no_lut` when
  asked for (or still set at issue) without a LUT for that year; ignored on
  other documents.
* `reverse_charge` (write, optional): registered clients in India only
  (`422 reverse_charge_not_allowed` otherwise). Taxes are computed and shown;
  `grand_total` and `net_receivable` leave them out.
* GST registrations: `lut_arn` (15 letters / digits) and `lut_fy_start_year`
  (PATCH, together or both null; regular registrations only:
  `422 required` / `not_allowed`). The ARN is frozen into the supplier
  snapshot of documents issued under it and printed with the declaration.
* PDF: the CGST Rules r.46 declarations ("SUPPLY TO SEZ UNIT OR SEZ DEVELOPER
  FOR AUTHORISED OPERATIONS UNDER BOND OR LETTER OF UNDERTAKING WITHOUT
  PAYMENT OF INTEGRATED TAX", "… ON PAYMENT OF INTEGRATED TAX", the export
  equivalents) and, under reverse charge, taxes marked "payable by the
  recipient".
* Reports: GST summary rows `B2B_REVERSE_CHARGE`, `SEZ`, `EXPORT` besides
  `B2B` / `B2C`; the summary's `tax` leaves reverse-charge tax out. GSTR-1:
  SEZ → `SEWOP` under LUT, else `SEWP`; exports → `exp` `WOPAY` / `WPAY`;
  reverse charge → `rchrg` `Y`.

### RA (running account) bills

`is_ra_bill: true` on `POST /documents` (or `PATCH` of a draft) makes a tax
invoice, bill of supply or proforma an RA bill against its project's BOQ
(otherwise `422` on `is_ra_bill` / `project_id`).

- Every line names a `boq_item_id`, once (`lines[i].boq_item_id`: `required`,
  `duplicate_boq_item`); extra work goes into the BOQ as a variation item.
  Lines may leave out description, unit, SAC/HSN, rate and GST rate (BOQ).
- `ra_sequence` (RA bill 1, 2, 3 ...) runs per project and document type and is
  given when the draft is created. One RA draft per project and type may be
  open (`409 ra_draft_exists`). A cancelled RA bill keeps its number; if it was
  the latest, its replacement reuses it.
- Each line returns `quantity` (this bill), `prev_cumulative_qty` (billed
  before it) and `up_to_date_qty`. *Billed* means lines of issued tax invoices
  and bills of supply, RA or not; proformas, drafts, cancelled documents and
  credit / debit notes do not count. The snapshot is retaken at issue.
- BOQ cap, for every tax invoice / bill of supply naming BOQ items and every RA
  bill: billed + this document must not pass the contract quantity unless the
  item is a variation (`422 exceeds_boq_quantity` on `lines[i].quantity`).
  Checked on every save and again at issue with the BOQ rows locked, so bills
  issued concurrently cannot pass it together.
- Converting an RA proforma gives an RA invoice with its own number; credit
  and debit notes are never RA bills. List filter: `is_ra_bill=true`.
- The PDF title reads "Tax Invoice · RA Bill No. 3" with Item / Previous qty /
  This bill qty / Up to date qty columns.

### Issue
```http
POST /api/v1/documents/0192f5d0-.../issue
If-Match: "v4"
Idempotency-Key: 9b0e...
```
→ `200` with the issued document (`doc_number: "INV/0042"`) ·
`409 document_not_draft` · `409 series_missing` (no active series for this
FY) · `422 no_lines` · `412` stale version · `403 email_not_verified` (the
issuer has not confirmed their email address).

Built in Phase 1.6. Issuing recomputes the totals first (current project
settings and advance outstanding), then takes the number under a row lock on
the series and freezes supplier and party snapshots. Other actions:
`cancel {reason}` (`409 not_cancellable`, `document_settled`,
`has_issued_notes`, `credit_note_allocated`); `accept` / `decline`
(`409 not_a_quotation`, `not_issued`); `convert {to, doc_date}` (QUOTATION →
PROFORMA / TAX_INVOICE / BILL_OF_SUPPLY, PROFORMA → TAX_INVOICE / BILL_OF_SUPPLY;
`422 not_convertible`); `credit-notes` / `debit-notes {doc_date, notes, lines?}`
against an issued TAX_INVOICE (lines copied when omitted; `409
not_an_issued_invoice`; at issue `409 original_not_issued`, `422
credit_exceeds_original`). Issue, convert and notes need `Idempotency-Key`;
issue, cancel, accept and decline need `If-Match`.

---

## 6. Payments & expenses

| Method & path | Purpose |
|---|---|
| `GET/POST /payments` | Record a receipt, optionally allocating it in the same request |
| `GET /payments/{id}` | With allocations |
| `POST /payments/{id}/allocations` · `DELETE /allocations/{id}` | Allocate leftover amount / unwind; an item settles a `document_id` or a `retention_release_id` |
| `POST /payments/{id}/void` | `{reason}`, removes its allocations (audited) |
| `GET/POST /documents/{id}/allocations` | GET: what settled a document, or what a credit note was applied to (`applied` / `unapplied`). POST (issued credit notes only, idempotent): apply it to issued invoices / debit notes of the same party (`409 not_an_issued_credit_note`, `422 allocation_exceeds_credit`, `allocation_exceeds_outstanding`) |
| `GET/POST /expenses` · `GET/PATCH /expenses/{id}` · `POST /expenses/{id}/void` | Site/office expenses with bill attachment. Built in Phase 2.3: the server computes `total_amount` (taxable + GST) and `balance`; `amount_paid` ≤ total (`exceeds_total`) with a `payment_mode` once paid; vendor must be a vendor (`not_a_vendor`); ITC needs GST (`no_gst`); filters `category=A,B`, project, vendor, dates, `payment_state`; voided expenses are read-only (`409 expense_voided`); never deleted |

```json
POST /api/v1/payments
{
  "party_id": "0192f5c4-...",
  "project_id": "0192f5c4-...",
  "payment_date": "2026-10-25",
  "amount": "300000.00",
  "mode": "BANK_TRANSFER",
  "reference": "UTR SBIN0026102500123",
  "allocations": [
    { "document_id": "0192f5d0-...", "amount": "300000.00" }
  ]
}
```
Over-allocation fails with `422 allocation_exceeds_outstanding`. The database
enforces this too, so concurrent requests can't double-settle an invoice.

Built in Phase 2.1. Codes: `422 allocation_exceeds_outstanding`,
`allocation_exceeds_payment`, `document_not_settleable` (only issued invoices,
bills of supply, debit notes), `party_mismatch`, `duplicate`; `409
already_allocated`, `payment_voided`. Payment responses carry `allocated`,
`unallocated` and `allocations` (with `doc_number`). Void needs `If-Match`
and a reason; it unwinds the allocations first. Payments are never deleted.

### Retention releases (Phase 3.3)

Retention is deducted from what the client pays on each bill (GST was charged
on the full value then). When the client releases it, record a **retention
release**: money now due, not a tax document and not new billing. It is
collected like an invoice, by allocating payments to it.

| Method & path | Purpose | Permission |
|---|---|---|
| `GET /projects/{id}/retention` | Per book (`GST` = tax invoices, `NON_GST` = bills of supply): `deducted`, `released`, `available` | read |
| `GET/POST /retention-releases` | List (`project_id`, `party_id`, `status`, `book`, `release_date_from/to`); create (idempotent) | read / issue |
| `GET /retention-releases/{id}` | With `amount_settled`, `outstanding`, `allocations` | read |
| `POST /retention-releases/{id}/cancel` | `{reason}`, `If-Match`; only with nothing allocated (`409 release_settled`) | issue |

```json
POST /api/v1/retention-releases
{ "project_id": "0192f5c4-...", "release_date": "2026-11-05", "due_date": "2026-11-20",
  "amount": "20000.00", "reference": "SKY/RET/12" }
```
- The party is the project's client. `book` defaults to GST while any GST
  retention is held. At most `available` can be released (`422
  exceeds_retention_held`, `nothing_to_release`); releasing locks the project
  row, so parallel releases cannot over-release.
- Settle with a payment: an allocation item takes `retention_release_id`
  instead of `document_id` (exactly one: `422 one_target`). Credit notes do
  not settle releases (`not_allowed`); a cancelled release cannot be settled
  (`release_cancelled`). The database keeps `amount_settled` and refuses
  over-settlement, as for invoices.
- A bill whose retention has been released cannot be cancelled until the
  release is (`409 retention_released`).
- Unsettled releases appear in receivables, outstanding and the project
  report (`retention_held` = deducted − released, `retention_released`);
  payments allocated to them count as collected in their book.

### Payment reminders (W.2)

Emails to a client about an unpaid issued invoice, bill of supply or debit
note. **Automatic** (Celery beat, 04:00 UTC = 09:30 IST; each tenant's
"today" in its own time zone): 3 days before the due date (`BEFORE_DUE`), on
it (`ON_DUE`), then 7, 15 and 30 days after (`OVERDUE_7`, `OVERDUE_15`,
`OVERDUE_30`). Only the latest stage due and not yet sent goes out, so a
missed day never sends a burst; a unique index sends each stage at most once
per bill. Skipped: bills without a due date, settled bills, clients without
an email, clients with `parties.reminders_enabled = false`. A mail-server
failure logs nothing, so the next run tries again.

| Method & path | |
|---|---|
| `GET /documents/{id}/reminders` | What went out, newest first: `stage`, `sent_to`, `amount_due`, `sent_by_name` (null = the daily job), `sent_at` |
| `POST /documents/{id}/reminders` | Send one now (`MANUAL`; Idempotency-Key; `payments.record`: owner, admin, accountant) → `201`. `409 not_receivable` (not an issued receivable), `409 nothing_due`, `409 reminded_recently` (one a day per bill), `422 no_client_email` (field `party.email`), `503 email_unavailable` (nothing logged). Sent even if the client's automatic reminders are off |

`PATCH /parties/{id}` takes `reminders_enabled` (default `true`). Table
`payment_reminders` is append-only (the app role cannot update it); across
tenants the job sees only active tenant ids and time zones
(`active_tenants()`, SECURITY DEFINER, owner-only policy on `tenants`).

### TDS certificates (Phase 3.4)

Income-tax TDS (s.194C) deducted by clients is certified quarterly on Form
16A. Record each certificate and reconcile it against the TDS on our bills
(`GET /reports/tds-reconciliation`, §8).

| Method & path | Purpose | Permission |
|---|---|---|
| `GET/POST /tds-certificates` | List (`party_id`, `fy_start_year`, `quarter`, `deductor_tan`); record (idempotent) | read / record payments |
| `GET/PATCH/DELETE /tds-certificates/{id}` | Correct (`If-Match`) or delete a wrong entry (audited) | read / record payments |

Fields: `party_id` (the client, a customer), `deductor_tan` (upper-cased,
`422 invalid_tan`), `section` (default `194C`), `fy_start_year` (2026 = FY
2026-27), `quarter` (1 = Apr-Jun ... 4 = Jan-Mar), `certificate_number`
(unique per TAN: `409 certificate_exists`), `certificate_date`,
`amount_credited`, `tds_amount`, `notes`. A certificate records the client's
paper, not a posting of ours, so unlike documents it may be edited or
deleted. GST TDS (s.51) is not reconciled yet: it is deducted at payment, not
at billing.

---

## 7. Files

| Method & path | Purpose |
|---|---|
| `POST /attachments` | `{filename, content_type, size_bytes}` → `201 {attachment, upload_url, upload_headers, expires_in}` (presigned PUT, 5-minute expiry) |
| `POST /attachments/{id}/complete` | Server verifies the object (size, type, magic bytes) → `202`; a task hashes and virus-scans it |
| `GET /attachments/{id}` | Metadata + short-lived download URL (only when AVAILABLE) |

Built in L.3 (2026-10-21):

* Types: PDF, JPEG, PNG, WebP; 1 byte to 20 MB (`422` on `content_type` /
  `size_bytes`). Roles: everyone but VIEWER may upload (`files.upload`);
  every member may read. `Idempotency-Key` honoured when sent.
* The presigned PUT signs `Content-Type` and `Content-Length`, so storage
  refuses any other type or size (`403 SignatureDoesNotMatch`). The client
  sends `upload_headers` and no `Authorization` header. Storage keys are
  `tenants/<tenant>/uploads/<uuid7>.<ext>`: no client text; the filename
  (path and control characters removed) lives only in the row.
* `complete` (the uploader only; others get 404): `409 upload_missing` if
  nothing was uploaded; `422 upload_mismatch` (object deleted) if size, type
  or the first bytes differ from what was announced; otherwise `202` and the
  attachment stays `PENDING` until the task makes it `AVAILABLE` (SHA-256
  stored) or `QUARANTINED` (malware or changed content; object deleted).
  Clients poll `GET /attachments/{id}`. Completing again is harmless.
* Virus scan through ClamAV (clamd `INSTREAM`, `CLAMD_HOST` / `CLAMD_PORT`);
  scanner unreachable → the task retries with backoff and the file stays
  `PENDING`. Without `CLAMD_HOST` files are not scanned (development; a
  warning is logged); production settings refuse to start without it.
* Only `AVAILABLE` files can be linked (an expense's `attachment_id`:
  `422 not_available`) or downloaded. Download links last 5 minutes and carry
  a header-safe `Content-Disposition: inline` with the original name.
* Browsers upload straight to the bucket: `manage.py setup_storage` creates
  it if needed and allows `PUT` / `GET` from `S3_CORS_ORIGINS`.

---

## 8. Reports (web dashboard and owner mobile app)

All amounts are strings. Permission `reports.view` (OWNER, ADMIN, ACCOUNTANT,
VIEWER; site engineers get 403). Period reports accept `from`, `to`
(`YYYY-MM-DD`; default 1 April of the current financial year to today, at most
5 years, `422 invalid_dates` / `range_too_long`) and `book=GST|NON_GST|ALL`
(default `ALL`).

| Method & path | Returns |
|---|---|
| `GET /reports/summary` | Billed, taxable, tax, collected, expenses for the period and the previous one (trend), plus outstanding now |
| `GET /reports/billing-by-month` | Series for charts, split by book |
| `GET /reports/receivables` | Outstanding by party with ageing buckets (not due / 1–30 / 31–60 / 61–90 / 90+ days past due), plus `totals`; `book` only |
| `GET /reports/projects` · `GET /reports/projects/{id}` | Contract value vs billed, retention held, TDS deducted, advance recovered, outstanding, cost → margin |
| `GET /reports/tds-reconciliation?fy=2026` | Per client and quarter: income-tax TDS on issued tax invoices / bills of supply (by bill date) vs Form 16A certificates recorded; `difference`, `status` (`MATCHED`, `SHORT`, `EXCESS`, `NOT_RECEIVED`), `certificate_due` (15 Aug / 15 Nov / 15 Feb / 15 Jun) and `overdue`; optional `party_id`; `fy` defaults to this FY |
| `GET /reports/gst-summary?period=2026-10` | GST documents' outward supplies by B2B/B2C and rate, CGST/SGST/IGST/cess, plus `totals` (basis for GSTR-1/3B) |
| `GET /parties/{id}/statement` | A client's statement of account (`from` / `to`, default this FY to today): `opening_balance`, `entries` (date, kind, reference, description, debit, credit, running `balance`, links to the document / payment / release), `total_debit`, `total_credit`, `closing_balance`; positive = the client owes. 404 for another tenant's party |
| `POST /exports` · `GET /exports` · `GET /exports/{id}` | Async CSV / XLSX registers, the statement of account (also PDF) and GSTR-1 JSON; download via presigned URL |

Rules behind the numbers:

- Only issued documents count; cancelled ones count nowhere, quotations are
  not revenue, credit notes count negative (by document date).
- *Previous period*: the same number of calendar months before when the
  period is whole months (October → September, a quarter → the quarter
  before), otherwise the same number of days.
- *Collected*: with `book=ALL`, every recorded payment in the period (including
  advances not yet allocated); with a book, what was allocated to that book's
  documents.
- *Outstanding* and receivables are as of today, whatever the period.
- *Statement of account* (W.1): a bill counts at its total less the retention
  and TDS deducted on it (= net receivable + advance recovered): retention is
  owed later and appears as a debit when released; TDS is paid to the
  government for the client; a mobilisation advance is a payment the client
  made, so the bills' "advance recovered" only adjusts it and is not
  subtracted again. Credit notes and payments (allocated or not) are credits.
  Cancelled bills / releases and voided payments count nowhere. Same day:
  bills, releases, credit notes, then payments.
- *Project cost*: recorded expenses on the project; their GST counts as cost
  unless input tax credit can be claimed (`itc_eligible`). Margin =
  billed taxable value − cost.

The mobile app needs only `/auth/*`, `/me`, `/reports/*`, read-only
`/documents`, `/parties`, `/projects`, `/payments`, and `/documents/{id}/pdf`.
Same API, same permissions.

---

### Main dashboard (W.6, 2026-11-02)

`GET /reports/dashboard?from=&to=&book=` (reports.view; `from`/`to`/`book` as
for `/reports/summary`) answers the dashboard in one request:

* `totals` / `previous` (the period before, as in the summary): `billed`,
  `collected`, `expenses` and `margin` (billed taxable value less cost; expense
  GST counts as cost unless input tax credit is claimable, as in the project
  report) for the period; `outstanding` and `overdue` (past due date) are today's.
* `months`: billed and collected for the 12 months up to `to` (empty months
  included, oldest first).
* `overdue`: `count` of past-due bills and the 10 oldest (number, client,
  due date, `days_overdue`, `outstanding`, `party_has_email`,
  `last_reminder_at`); remind with `POST /documents/{id}/reminders` (W.2).
* `losing_projects`: at most 5 projects whose cost exceeds billed taxable value.
* `drafts`: `count` and the 5 waiting longest.

### Exports (E.1, 2026-10-22)

`POST /exports {kind, format, params}` → `202` with the export (`PENDING`); a
Celery task writes the file to storage and marks it `READY` (or `FAILED` with
`error`). Poll `GET /exports/{id}`; `download_url` (5 minutes,
`Content-Disposition: attachment`) appears once `READY`. `GET /exports`
lists the caller's latest 20. Rows and files are deleted after 7 days.

| `kind` | `params` | Content |
|---|---|---|
| `DOCUMENTS` | `from`, `to`, `book` | Invoice register: every issued / cancelled document by date (drafts never) |
| `PAYMENTS` | `from`, `to` | Payments with allocated / unallocated |
| `EXPENSES` | `from`, `to` | Expenses with GST, ITC, paid, balance |
| `RECEIVABLES` | `book` | What clients owe today, by age |
| `GSTR1` (format `JSON`) | `gst_registration_id`, `period` (`YYYY-MM`) | GSTR-1 for one regular registration and month (E.2, below) |
| `BOQ` | `project_id` | One project's BOQ: contract, billed, balance (quantity and value), progress %, variation (as `GET /projects/{id}/boq-progress`) |
| `STATEMENT` (CSV, XLSX or PDF) | `party_id`, `from`, `to` | One client's statement of account: opening balance, entries, closing balance (W.1, below). The only kind made as a PDF |
| `PROJECTS` | none | Project margins to date: contract value, billed, retention, TDS, advance recovered, outstanding, cost, margin (as `GET /reports/projects`) |

* `format`: `CSV` (UTF-8 with BOM, ISO dates, plain `1234.50` amounts) or
  `XLSX` (real dates and numbers, `#,##0.00`). Quantities and percentages
  are plain decimals without trailing zeros (`42.5`; XLSX `#,##0.###`).
  A `BOQ` request for a project the company does not have is `422`
  (`params.project_id`). `from` / `to` default to this
  financial year to today and are stored filled in. Over 100,000 rows →
  `FAILED` ("choose a shorter period").
* User text cannot run as a spreadsheet formula: CSV text cells starting with
  `= + - @` get a leading apostrophe; XLSX text cells are stored as strings.
* GSTR-1 (E.2): the GST offline tool's JSON shape (`version` `GST3.2.4`,
  `hash` `"hash"`, `fp` `MMYYYY`, dates `DD-MM-YYYY`, amounts as numbers with
  2 decimals written straight from Decimal). From the issued tax invoices,
  credit and debit notes dated in the month: `b2b` / `cdnr` (recipient has a
  GSTIN; SEZ → `SEWP` / `SEWOP`), `b2cl` / `cdnur` (inter-State to
  unregistered over ₹1,00,000, notes following their invoice), `exp`
  (overseas recipients), `b2cs` (other B2C, netted by supply type, place of
  supply and rate), `nil` (0 % lines, reported as nil-rated), `hsn`
  split into `hsn_b2b` / `hsn_b2c` (services: UQC `NA`, quantity 0; goods:
  unit mapped to a UQC, else `OTH`), `doc_issue` (per series: first / last
  number, total, cancelled). Items are one per rate, `num` = rate × 100 + 1.
  Checks: registration must be `REGULAR`; months from May 2025, not in the
  future; format must be `JSON` (`422` on `params.*` / `format`). Every file
  carries warnings, first of all to import it into the offline tool and
  check it before filing (no official schema was available to test
  against); others flag missing HSN codes, units without a UQC, 0 % lines,
  negative HSN / B2C rows, short HSN codes on B2B, SEZ / export documents.
* Permission `reports.view`; each user sees only their own exports (another
  member's: 404). Rate limit 20 per hour per user. `Idempotency-Key`
  honoured when sent. Every export is in the audit trail (who exported what).

## 9. Operational endpoints

| Path | Purpose |
|---|---|
| `GET /healthz` | Liveness (no dependencies) |
| `GET /readyz` | Database + Redis reachable |
| `GET /api/v1/schema/` | OpenAPI document (auth required outside dev) |

---

## 10. Client portal (W.5b, 2026-11-02)

For people at a client, signed in with role `CLIENT` (portal users, §3;
password + emailed code, §2). Staff tokens get `403` here; client tokens get
`403` on every staff endpoint. Everything is the client's own, and the
database enforces it too (RLS `client_scope`): another client's or another
tenant's id is `404`. Responses leave out our internals (registrations,
series, catalog references, notes, who did what).

| Method & path | |
|---|---|
| `GET /portal/me` | `{business: {legal_name, trade_name}, client: {id, display_name, gstin}}` |
| `GET /portal/documents` | Issued, cancelled, accepted and declined documents (never drafts), cursor-paginated, newest first; `?doc_type=A,B&status=&project_id=&ordering=` (`doc_date`, `doc_number`). Rows: number, dates, `valid_until`, project, RA sequence, `totals` (incl. `amount_settled`, `outstanding`) |
| `GET /portal/documents/{id}` | With `lines`, `place_of_supply` and `terms`; `ETag` |
| `GET /portal/documents/{id}/pdf` | `302` to a short-lived link, `?as=link` → `200 {url, expires_in}`; `202` while it is being made |
| `POST /portal/documents/{id}/accept` · `/decline` | A quotation, with `If-Match` (`428` / `412`): → ACCEPTED / DECLINED (the audit log records who). `409 quotation_expired` (after `valid_until`, the business's date), `not_issued` (already answered or cancelled), `not_a_quotation` |
| `GET /portal/payments` | Recorded payments (not voided), cursor-paginated: date, amount, mode, reference, project and the bills each settled |
| `GET /portal/statement?from=&to=` | The statement of account, the same as the business's (§8, W.1) |
| `GET /portal/projects` · `GET /portal/projects/{id}/boq-progress` | The client's projects; contract vs billed per BOQ item (the same as `/projects/{id}/boq-progress`) |

