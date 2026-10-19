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
(unlike page numbers).

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

### Idempotency
* Required on: `POST /documents`, `/documents/{id}/issue`, `/payments`,
  `/expenses`, `/documents/{id}/credit-notes`, signup.
* Header `Idempotency-Key: <uuid>`, generated once per user action by the client
  and reused on retries.
* Same key + same body → the original response is replayed (with
  `Idempotent-Replayed: true`). Same key + different body → 422. Keys expire
  after 24 h.

### Rate limits
Response headers `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`.
See the architecture doc §6 for the limits.

---

## 2. Authentication

| Method & path | Purpose |
|---|---|
| `POST /auth/signup` | Create user + first tenant (the user becomes OWNER). Email verification required before issuing documents. |
| `POST /auth/verify-email` | Confirm email with a one-time token. |
| `POST /auth/login` | `{email, password}` → either `{mfa_required: true, mfa_token}` or `{tenants: [...], ...tokens}` |
| `POST /auth/mfa/verify` | `{mfa_token, code}` → tokens |
| `POST /auth/token/refresh` | Rotates the refresh token (cookie for web, body for mobile) → new access + refresh |
| `POST /auth/switch-tenant` | `{tenant_id}` → new tokens scoped to that tenant (membership checked) |
| `POST /auth/logout` | Revoke the current session |
| `GET /auth/sessions` · `DELETE /auth/sessions/{id}` | List / revoke your devices |
| `POST /auth/password/forgot` · `POST /auth/password/reset` | Reset flow; always returns 202 (no account enumeration) |
| `POST /auth/mfa/setup` · `POST /auth/mfa/enable` · `POST /auth/mfa/disable` | TOTP enrolment (disable requires password + code) |
| `GET /me` · `PATCH /me` | Profile, memberships |

Access token claims: `sub` (user), `tid` (tenant), `role`, `sid` (session
family), `amr` (`["pwd"]` or `["otp","pwd"]`), `iss`, `iat`, `exp` (10 min),
`typ`. HS256 only, `kid` in the header for key rotation.

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
* Not yet built: `verify-email`, `password/forgot|reset`, `PATCH /me`, rate
  limit headers, `Idempotency-Key` on signup (see PROGRESS.md).

---

## 3. Tenant administration (OWNER / ADMIN)

| Method & path | Purpose |
|---|---|
| `GET /tenant` · `PATCH /tenant` | Current business profile |
| `GET/POST /members` · `PATCH/DELETE /members/{id}` | Invite by email, change role, revoke. Built: `GET`, `PATCH {role}`, `DELETE` (→ REVOKED, idempotent). Errors: `403 permission_denied`, `owner_protected`, `cannot_modify_self`; `409 last_owner`, `member_revoked`; `404` for other tenants' members. `POST` (invite) pending a decision, see PROGRESS.md |
| `GET/POST /gst-registrations` · `GET/PATCH /gst-registrations/{id}` | Our GSTINs (one per state) |
| `GET/POST /document-series` · `PATCH /document-series/{id}` | Number series per registration, doc type and FY. `next_number` can be changed only when nothing has been issued from the series yet. |
| `GET /audit-log?table=documents&row_id=...` | Change history (OWNER/ADMIN) |

---

## 4. Master data

| Method & path | Notes |
|---|---|
| `GET/POST /parties` · `GET/PATCH /parties/{id}` | `?is_customer=true&q=...`. GSTIN validated (format + checksum). Archive with `PATCH {is_active: false}`; no delete. |
| `GET/POST /projects` · `GET/PATCH /projects/{id}` | `?status=ACTIVE&client_party_id=...` |
| `GET/POST /projects/{id}/boq-items` · `PATCH/DELETE /boq-items/{id}` | Bulk import: `POST /projects/{id}/boq-items:import` (CSV/XLSX, validated, all-or-nothing). Delete only if never billed. |
| `GET/POST /catalog-items` · `PATCH/DELETE /catalog-items/{id}` | Reusable items and rates |

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
| `GET /documents/{id}/pdf` | 302 to a short-lived presigned URL (generated async after issue; drafts render a "DRAFT" watermark on demand) | read |
| `POST /documents/{id}/send` | Email the PDF to the party (queued) | issue |
| `POST /documents:preview-totals` | Run the tax engine on an unsaved payload (live totals while typing) | drafts |

### List filters
`doc_type`, `status`, `book=GST|NON_GST|ALL` (maps to `is_gst_document`),
`party_id`, `project_id`, `doc_date_from/to`, `due_date_to`,
`payment_state=UNPAID|PARTIAL|PAID`, `q`.

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
site state) and returns them:

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

### Issue
```http
POST /api/v1/documents/0192f5d0-.../issue
If-Match: "v4"
Idempotency-Key: 9b0e...
```
→ `200` with the issued document (`doc_number: "INV/0042"`) ·
`409 document_not_draft` · `409 series_missing` (no active series for this
FY) · `422 no_lines` · `412` stale version.

---

## 6. Payments & expenses

| Method & path | Purpose |
|---|---|
| `GET/POST /payments` | Record a receipt, optionally allocating it in the same request |
| `GET /payments/{id}` | With allocations |
| `POST /payments/{id}/allocations` · `DELETE /allocations/{id}` | Allocate leftover amount / unwind |
| `POST /payments/{id}/void` | `{reason}`, removes its allocations (audited) |
| `GET/POST /expenses` · `GET/PATCH /expenses/{id}` · `POST /expenses/{id}/void` | Site/office expenses with bill attachment |

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

---

## 7. Files

| Method & path | Purpose |
|---|---|
| `POST /attachments` | `{filename, content_type, size_bytes}` → `{id, upload_url, upload_headers}` (presigned PUT, 5-minute expiry) |
| `POST /attachments/{id}/complete` | Server verifies the object (size, magic bytes, hash), queues a malware scan |
| `GET /attachments/{id}` | Metadata + short-lived download URL (only when AVAILABLE) |

---

## 8. Reports (web dashboard and owner mobile app)

All amounts are strings; every report accepts `from`, `to` and `book=GST|NON_GST|ALL`.

| Method & path | Returns |
|---|---|
| `GET /reports/summary` | Billed, tax, collected, outstanding, expenses, for the period and the previous one (trend) |
| `GET /reports/billing-by-month` | Series for charts, split by book |
| `GET /reports/receivables` | Outstanding by party with ageing buckets (not due / 1–30 / 31–60 / 61–90 / 90+) |
| `GET /reports/projects` · `GET /reports/projects/{id}` | Contract value vs billed, retention held, TDS deducted, advance recovered, outstanding, expenses → margin |
| `GET /reports/gst-summary?period=2026-10` | Outward supplies by rate, B2B/B2C, CGST/SGST/IGST totals (basis for GSTR-1/3B) |
| `POST /exports` · `GET /exports/{id}` | Async CSV/XLSX/GSTR-1 JSON export; download via presigned URL |

The mobile app needs only `/auth/*`, `/me`, `/reports/*`, read-only
`/documents`, `/parties`, `/projects`, `/payments`, and `/documents/{id}/pdf`.
Same API, same permissions.

---

## 9. Operational endpoints

| Path | Purpose |
|---|---|
| `GET /healthz` | Liveness (no dependencies) |
| `GET /readyz` | Database + Redis reachable |
| `GET /api/v1/schema/` | OpenAPI document (auth required outside dev) |
