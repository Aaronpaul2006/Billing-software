-- =============================================================================
-- Construction Billing Platform — reference PostgreSQL schema
--
-- Target:   PostgreSQL 17+
-- Tenancy:  shared database, shared schema, tenant_id on every tenant-owned row,
--           enforced by Row-Level Security (RLS) + composite foreign keys.
--
-- This file is the source of truth for the data model. The Django app mirrors
-- it: plain tables/columns/CHECKs come from Django models; RLS policies,
-- triggers, composite FKs, grants and views are applied with RunSQL migrations
-- copied from here. See docs/01-architecture.md.
--
-- Conventions
--   * ids are uuid (the app generates UUIDv7, so they sort by creation time)
--   * money is numeric(14,2), quantities numeric(14,3), rates numeric(5,2)
--     — never float
--   * enums are text + CHECK (easy to evolve, maps 1:1 to Django choices)
--   * issued financial documents are immutable; corrections are new documents
--   * nothing financial is hard-deleted; it is cancelled / voided / archived
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- 0. Roles
--    billing_owner : owns the tables, runs migrations (created by infra)
--    billing_app   : what the running API / workers connect as.
--                    NOT the table owner, NOBYPASSRLS → always subject to RLS.
--    In production a LOGIN user is granted membership in billing_app.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'billing_app') THEN
    CREATE ROLE billing_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 1. Request context
--    The API sets these per transaction with set_config(..., is_local => true)
--    (i.e. SET LOCAL), so they can never leak to the next request that reuses
--    a pooled connection. Unset → NULL → RLS matches no rows (fail closed).
-- -----------------------------------------------------------------------------
CREATE FUNCTION app_current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE FUNCTION app_current_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

-- Client-portal sessions (role CLIENT) only: the client (party) they belong to.
CREATE FUNCTION app_current_party() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.party_id', true), '')::uuid
$$;

-- True in a client-portal session. PL/pgSQL on purpose: the planner cannot
-- see inside it, so `NOT app_portal_session() OR <scope>` in the client_scope
-- policies gets an ordinary row estimate. Written as `app_current_party() IS
-- NULL` it was guessed at 0.5 % of rows, and staff reports chose nested loops
-- that took seconds on a large company (W.7 speed check).
CREATE FUNCTION app_portal_session() RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN NULLIF(current_setting('app.party_id', true), '') IS NOT NULL;
END $$;

-- India's financial year starts 1 April: 2026-05-10 → 2026, 2027-02-01 → 2026.
CREATE FUNCTION fy_start_year(d date) RETURNS smallint
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT (EXTRACT(YEAR FROM d)::int - CASE WHEN EXTRACT(MONTH FROM d) < 4 THEN 1 ELSE 0 END)::smallint
$$;

-- =============================================================================
-- 2. Global tables (identity; not owned by a single tenant)
-- =============================================================================

CREATE TABLE users (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email              citext NOT NULL UNIQUE,
  email_verified_at  timestamptz,                         -- NULL until the address is confirmed
  password_hash      text NOT NULL,                       -- argon2id encoded string
  full_name          text NOT NULL CHECK (char_length(full_name) BETWEEN 1 AND 200),
  phone              text CHECK (phone ~ '^\+?[0-9]{10,15}$'),
  mfa_enabled        boolean NOT NULL DEFAULT false,
  mfa_secret_enc     bytea,                               -- TOTP secret, envelope-encrypted by the app
  mfa_recovery_codes text[] NOT NULL DEFAULT '{}',        -- SHA-256 (hex) of unused one-time recovery codes
  mfa_last_used_step bigint,                              -- last accepted TOTP time step (no code replay)
  -- Client-portal sign-in: a 6-digit code emailed after the password (W.5).
  email_code_hash       text,                             -- HMAC of the pending code; NULL = none
  email_code_expires_at timestamptz,
  email_code_attempts   integer NOT NULL DEFAULT 0 CHECK (email_code_attempts >= 0),
  status             text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'LOCKED', 'DISABLED')),
  failed_login_count integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
  locked_until       timestamptz,
  last_login_at      timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT mfa_enabled OR mfa_secret_enc IS NOT NULL)
);

CREATE TABLE tenants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  legal_name  text NOT NULL CHECK (char_length(legal_name) BETWEEN 1 AND 200),
  trade_name  text,
  pan         char(10) CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
  status      text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')),
  plan        text NOT NULL DEFAULT 'FREE',
  timezone    text NOT NULL DEFAULT 'Asia/Kolkata',
  -- Bills at or above it need an owner's approval before others issue them (Part B).
  approval_limit numeric(14,2) CHECK (approval_limit IS NULL OR approval_limit > 0),
  version     integer NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- A user can belong to several tenants (e.g. an accountant serving many firms).
-- Role CLIENT is a person at one of the tenant's clients using the client
-- portal (W.5): party_id names that client (foreign key after parties, §3).
CREATE TABLE memberships (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants (id),
  user_id     uuid NOT NULL REFERENCES users (id),
  role        text NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'ACCOUNTANT', 'SITE_ENGINEER', 'VIEWER', 'CLIENT')),
  party_id    uuid,
  status      text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('INVITED', 'ACTIVE', 'REVOKED')),
  invited_by  uuid REFERENCES users (id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, user_id),
  CHECK ((role = 'CLIENT') = (party_id IS NOT NULL))
);
CREATE INDEX memberships_user_idx ON memberships (user_id);

-- Refresh-token sessions. Only a SHA-256 of the opaque token is stored.
-- Rotation: each refresh issues a new row in the same family; presenting an
-- already-rotated token revokes the whole family (token theft detection).
-- Invitations to people with no account yet. The email carries a signed link
-- (7 days) to create the account and join; an account that exists gets an
-- INVITED membership instead. Signing up the normal way also finds them
-- (claim_email_invitations(), section 8).
CREATE TABLE email_invitations (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants (id),
  email        citext NOT NULL CHECK (char_length(email) <= 254),
  role         text NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'ACCOUNTANT', 'SITE_ENGINEER', 'VIEWER', 'CLIENT')),
  party_id     uuid,                                     -- CLIENT: the client (FK after parties)
  status       text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'ACCEPTED', 'REVOKED')),
  invited_by   uuid NOT NULL REFERENCES users (id),
  accepted_by  uuid REFERENCES users (id),
  expires_at   timestamptz NOT NULL DEFAULT now() + interval '7 days',
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  CHECK ((status = 'ACCEPTED') = (accepted_by IS NOT NULL)),
  CHECK ((role = 'CLIENT') = (party_id IS NOT NULL))
);
CREATE UNIQUE INDEX email_invitations_pending_uq ON email_invitations (tenant_id, email) WHERE status = 'PENDING';

CREATE TABLE auth_sessions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             uuid NOT NULL REFERENCES users (id),
  tenant_id           uuid REFERENCES tenants (id),       -- tenant the session is bound to
  family_id           uuid NOT NULL,
  refresh_token_hash  bytea NOT NULL UNIQUE CHECK (octet_length(refresh_token_hash) = 32),
  device_label        text,
  ip                  inet,
  user_agent          text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  expires_at          timestamptz NOT NULL,
  rotated_at          timestamptz,
  revoked_at          timestamptz,
  amr                 text[] NOT NULL DEFAULT '{}'         -- how the user signed in, kept across refreshes
);
CREATE INDEX auth_sessions_user_idx ON auth_sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX auth_sessions_family_idx ON auth_sessions (family_id);

-- =============================================================================
-- 3. Tenant-owned master data
--    Every table has UNIQUE (tenant_id, id) so children can use a composite FK
--    (tenant_id, x_id) → parent (tenant_id, id). Foreign-key checks bypass RLS
--    in PostgreSQL, so a plain FK on x_id alone would let tenant A reference
--    tenant B's row if it learned the uuid. The composite FK makes that
--    impossible at the database level.
-- =============================================================================

-- A business can hold one GST registration per state (or none).
CREATE TABLE gst_registrations (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants (id),
  registration_type  text NOT NULL CHECK (registration_type IN ('REGULAR', 'COMPOSITION', 'UNREGISTERED')),
  gstin              varchar(15) CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  state_code         char(2) NOT NULL CHECK (state_code ~ '^[0-9]{2}$'),
  legal_name         text NOT NULL,
  trade_name         text,
  address            jsonb NOT NULL,
  is_default         boolean NOT NULL DEFAULT false,
  is_active          boolean NOT NULL DEFAULT true,
  -- Letter of Undertaking (form GST RFD-11) for the financial year starting in
  -- lut_fy_start_year: zero-rated supplies (SEZ, exports) without paying IGST.
  lut_arn            text CHECK (lut_arn ~ '^[A-Z0-9]{15}$'),
  lut_fy_start_year  smallint CHECK (lut_fy_start_year BETWEEN 2017 AND 2100),
  version            integer NOT NULL DEFAULT 1,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  CHECK ((registration_type = 'UNREGISTERED') = (gstin IS NULL)),
  CHECK (gstin IS NULL OR substr(gstin, 1, 2) = state_code),
  CHECK ((lut_arn IS NULL AND lut_fy_start_year IS NULL) OR (lut_arn IS NOT NULL AND lut_fy_start_year IS NOT NULL))
);
CREATE UNIQUE INDEX gst_registrations_gstin_uq ON gst_registrations (tenant_id, gstin) WHERE gstin IS NOT NULL;
CREATE UNIQUE INDEX gst_registrations_default_uq ON gst_registrations (tenant_id) WHERE is_default;

CREATE TABLE parties (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants (id),
  is_customer     boolean NOT NULL DEFAULT true,
  is_vendor       boolean NOT NULL DEFAULT false,         -- suppliers and subcontractors
  display_name    text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
  legal_name      text,
  gst_treatment   text NOT NULL CHECK (gst_treatment IN ('REGISTERED', 'COMPOSITION', 'UNREGISTERED', 'CONSUMER', 'SEZ', 'OVERSEAS')),
  gstin           varchar(15) CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  pan             char(10) CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
  state_code      char(2) CHECK (state_code ~ '^[0-9]{2}$'),
  billing_address jsonb,
  email           citext,
  phone           text,
  reminders_enabled boolean NOT NULL DEFAULT true,     -- automatic payment reminders by email
  payment_terms_days smallint CHECK (payment_terms_days BETWEEN 0 AND 365),  -- B.5: new bills fall due this many days after the bill date
  is_active       boolean NOT NULL DEFAULT true,
  version         integer NOT NULL DEFAULT 1,
  created_by      uuid NOT NULL REFERENCES users (id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  CHECK (is_customer OR is_vendor),
  CHECK (gst_treatment NOT IN ('REGISTERED', 'COMPOSITION') OR gstin IS NOT NULL),
  CHECK (gstin IS NULL OR substr(gstin, 1, 2) = state_code)
);
CREATE INDEX parties_tenant_name_idx ON parties (tenant_id, display_name);
CREATE INDEX parties_name_trgm_idx ON parties USING gin (display_name gin_trgm_ops);
CREATE INDEX parties_gstin_idx ON parties (tenant_id, gstin) WHERE gstin IS NOT NULL;

-- Client-portal users and invitations name a client of their own tenant.
ALTER TABLE memberships
  ADD FOREIGN KEY (tenant_id, party_id) REFERENCES parties (tenant_id, id);
ALTER TABLE email_invitations
  ADD FOREIGN KEY (tenant_id, party_id) REFERENCES parties (tenant_id, id);

CREATE TABLE projects (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenants (id),
  code                  text NOT NULL CHECK (code ~ '^[A-Za-z0-9_-]{1,30}$'),
  name                  text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  client_party_id       uuid NOT NULL,
  gst_registration_id   uuid NOT NULL,                  -- which of our registrations bills this project
  site_address          jsonb,
  -- For works on immovable property the GST place of supply is where the
  -- property is located (IGST Act s.12(3)), so this decides CGST+SGST vs IGST.
  site_state_code       char(2) NOT NULL CHECK (site_state_code ~ '^[0-9]{2}$'),
  contract_value        numeric(14,2) CHECK (contract_value >= 0),
  retention_pct         numeric(5,2) NOT NULL DEFAULT 0 CHECK (retention_pct BETWEEN 0 AND 100),
  income_tax_tds_pct    numeric(5,2) NOT NULL DEFAULT 0 CHECK (income_tax_tds_pct BETWEEN 0 AND 100),  -- e.g. s.194C
  gst_tds_applicable    boolean NOT NULL DEFAULT false,                                               -- CGST Act s.51 (govt/PSU clients)
  mobilisation_advance  numeric(14,2) NOT NULL DEFAULT 0 CHECK (mobilisation_advance >= 0),
  advance_recovery_pct  numeric(5,2) NOT NULL DEFAULT 0 CHECK (advance_recovery_pct BETWEEN 0 AND 100),
  status                text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('PLANNED', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED')),
  start_date            date,
  end_date              date,
  version               integer NOT NULL DEFAULT 1,
  created_by            uuid NOT NULL REFERENCES users (id),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, code),
  FOREIGN KEY (tenant_id, client_party_id) REFERENCES parties (tenant_id, id),
  FOREIGN KEY (tenant_id, gst_registration_id) REFERENCES gst_registrations (tenant_id, id),
  CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
CREATE INDEX projects_client_idx ON projects (tenant_id, client_party_id);
CREATE INDEX projects_name_trgm_idx ON projects USING gin (name gin_trgm_ops);

-- Bill of Quantities: the priced item list of a contract. RA bills bill
-- progress against these items.
CREATE TABLE boq_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants (id),
  project_id    uuid NOT NULL,
  item_code     text NOT NULL CHECK (char_length(item_code) BETWEEN 1 AND 30),   -- e.g. "2.1.3"
  description   text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 2000),
  unit          text NOT NULL CHECK (char_length(unit) BETWEEN 1 AND 20),        -- cum, sqm, kg, nos
  sac_hsn       text CHECK (sac_hsn ~ '^[0-9]{4,8}$'),
  contract_qty  numeric(14,3) NOT NULL CHECK (contract_qty >= 0),
  rate          numeric(14,2) NOT NULL CHECK (rate >= 0),
  gst_rate      numeric(5,2) NOT NULL DEFAULT 18 CHECK (gst_rate BETWEEN 0 AND 50),
  is_variation  boolean NOT NULL DEFAULT false,         -- extra item / change order
  sort_order    integer NOT NULL DEFAULT 0,
  version       integer NOT NULL DEFAULT 1,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, project_id, item_code),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)
);

CREATE TABLE catalog_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants (id),
  name          text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  description   text,
  unit          text,
  sac_hsn       text CHECK (sac_hsn ~ '^[0-9]{4,8}$'),
  default_rate  numeric(14,2) CHECK (default_rate >= 0),
  gst_rate      numeric(5,2) NOT NULL DEFAULT 18 CHECK (gst_rate BETWEEN 0 AND 50),
  is_active     boolean NOT NULL DEFAULT true,
  version       integer NOT NULL DEFAULT 1,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

-- Variants of a catalog item (W.4), e.g. Brand: UltraTech, Grade: OPC 53. A
-- variant's rate is the item's default rate plus `rate_delta` (may be
-- negative). Bill lines name a variant of their own item only: the
-- three-column key below lets document_lines enforce that.
CREATE TABLE catalog_item_variants (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  catalog_item_id  uuid NOT NULL,
  attribute        text NOT NULL CHECK (char_length(attribute) BETWEEN 1 AND 50),
  value            text NOT NULL CHECK (char_length(value) BETWEEN 1 AND 100),
  rate_delta       numeric(14,2) NOT NULL DEFAULT 0,
  is_active        boolean NOT NULL DEFAULT true,
  version          integer NOT NULL DEFAULT 1,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, catalog_item_id, id),
  UNIQUE (tenant_id, catalog_item_id, attribute, value),
  FOREIGN KEY (tenant_id, catalog_item_id) REFERENCES catalog_items (tenant_id, id)
);

-- A saved quote / bill to start new drafts from (W.3), e.g. "2BHK interior
-- package". Lines are copied values (description, HSN / SAC, unit, quantity,
-- rate, GST %, discount), checked by the API; drafts made from a template go
-- through the normal draft rules, so nothing here is trusted for tax.
CREATE TABLE document_templates (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants (id),
  name        text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 100),
  doc_type    text NOT NULL CHECK (doc_type IN ('QUOTATION', 'PROFORMA', 'TAX_INVOICE', 'BILL_OF_SUPPLY')),
  valid_days  smallint CHECK (valid_days BETWEEN 1 AND 365),     -- quotations: valid until date + days
  notes       text CHECK (char_length(notes) <= 5000),
  terms       text CHECK (char_length(terms) <= 5000),
  lines       jsonb NOT NULL CHECK (jsonb_typeof(lines) = 'array'
                                    AND jsonb_array_length(lines) BETWEEN 1 AND 200),
  version     integer NOT NULL DEFAULT 1,
  created_by  uuid NOT NULL REFERENCES users (id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, name),
  CHECK (valid_days IS NULL OR doc_type = 'QUOTATION')
);

-- Uploaded files live in object storage; this is the metadata. The storage key
-- is generated by the server (never taken from the client).
CREATE TABLE attachments (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants (id),
  storage_key        text NOT NULL UNIQUE,
  original_filename  text NOT NULL CHECK (char_length(original_filename) BETWEEN 1 AND 255),
  content_type       text NOT NULL CHECK (content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')),
  size_bytes         bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 20971520),   -- 20 MiB
  sha256             bytea CHECK (octet_length(sha256) = 32),
  status             text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'AVAILABLE', 'QUARANTINED')),
  uploaded_by        uuid NOT NULL REFERENCES users (id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

-- How the business's bills look on paper (B.12): one row per business, made
-- on the first save. Logo and signature are uploaded images (attachments).
CREATE TABLE print_settings (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                uuid NOT NULL UNIQUE REFERENCES tenants (id),
  layout                   text NOT NULL DEFAULT 'DETAILED' CHECK (layout IN ('SIMPLE', 'DETAILED')),
  logo_attachment_id       uuid,
  signature_attachment_id  uuid,
  bank_account_name        text CHECK (char_length(bank_account_name) BETWEEN 1 AND 200),
  bank_name                text CHECK (char_length(bank_name) BETWEEN 1 AND 200),
  bank_account_number      text CHECK (bank_account_number ~ '^[0-9]{6,18}$'),
  bank_ifsc                text CHECK (bank_ifsc ~ '^[A-Z]{4}0[A-Z0-9]{6}$'),
  bank_branch              text CHECK (char_length(bank_branch) BETWEEN 1 AND 200),
  upi_id                   text CHECK (upi_id ~ '^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,63}$'),
  default_terms            text CHECK (char_length(default_terms) BETWEEN 1 AND 5000),
  version                  integer NOT NULL DEFAULT 1,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, logo_attachment_id) REFERENCES attachments (tenant_id, id),
  FOREIGN KEY (tenant_id, signature_attachment_id) REFERENCES attachments (tenant_id, id)
);

-- The ledger names the Tally export writes (B.16): one row per business, made
-- on the first save. Clients use their own names as ledgers.
CREATE TABLE tally_settings (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL UNIQUE REFERENCES tenants (id),
  sales_ledger     text NOT NULL DEFAULT 'Sales' CHECK (char_length(sales_ledger) BETWEEN 1 AND 200),
  cgst_ledger      text NOT NULL DEFAULT 'Output CGST' CHECK (char_length(cgst_ledger) BETWEEN 1 AND 200),
  sgst_ledger      text NOT NULL DEFAULT 'Output SGST' CHECK (char_length(sgst_ledger) BETWEEN 1 AND 200),
  igst_ledger      text NOT NULL DEFAULT 'Output IGST' CHECK (char_length(igst_ledger) BETWEEN 1 AND 200),
  cess_ledger      text NOT NULL DEFAULT 'Output Cess' CHECK (char_length(cess_ledger) BETWEEN 1 AND 200),
  round_off_ledger text NOT NULL DEFAULT 'Round Off' CHECK (char_length(round_off_ledger) BETWEEN 1 AND 200),
  tds_ledger       text NOT NULL DEFAULT 'TDS Receivable' CHECK (char_length(tds_ledger) BETWEEN 1 AND 200),
  gst_tds_ledger   text NOT NULL DEFAULT 'GST TDS Receivable' CHECK (char_length(gst_tds_ledger) BETWEEN 1 AND 200),
  retention_ledger text NOT NULL DEFAULT 'Retention Receivable' CHECK (char_length(retention_ledger) BETWEEN 1 AND 200),
  advance_ledger   text NOT NULL DEFAULT 'Client Advances' CHECK (char_length(advance_ledger) BETWEEN 1 AND 200),
  bank_ledger      text NOT NULL DEFAULT 'Bank Account' CHECK (char_length(bank_ledger) BETWEEN 1 AND 200),
  cash_ledger      text NOT NULL DEFAULT 'Cash' CHECK (char_length(cash_ledger) BETWEEN 1 AND 200),
  version          integer NOT NULL DEFAULT 1,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

-- =============================================================================
-- 4. Billing documents
--    ONE table for every billing document. "GST books", "estimates" and the
--    "combined view" are filters over it, not separate modules.
--
--    doc_type        GST document?   revenue?
--    QUOTATION       no              no   (an offer, not a sale)
--    PROFORMA        no              no
--    TAX_INVOICE     yes             yes  (RA bills of a registered contractor are tax invoices)
--    BILL_OF_SUPPLY  no              yes  (composition / unregistered supplier, exempt supply)
--    CREDIT_NOTE     yes             yes  (negative)
--    DEBIT_NOTE      yes             yes
-- =============================================================================

CREATE TABLE document_series (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants (id),
  gst_registration_id  uuid NOT NULL,
  doc_type             text NOT NULL CHECK (doc_type IN ('QUOTATION', 'PROFORMA', 'TAX_INVOICE', 'BILL_OF_SUPPLY', 'CREDIT_NOTE', 'DEBIT_NOTE')),
  fy_start_year        smallint NOT NULL CHECK (fy_start_year BETWEEN 2000 AND 2100),
  prefix               text NOT NULL DEFAULT '' CHECK (prefix ~ '^[A-Za-z0-9/-]{0,10}$'),
  next_number          integer NOT NULL DEFAULT 1 CHECK (next_number > 0),
  pad_width            smallint NOT NULL DEFAULT 4 CHECK (pad_width BETWEEN 1 AND 8),
  is_active            boolean NOT NULL DEFAULT true,
  version              integer NOT NULL DEFAULT 1,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, gst_registration_id, doc_type, fy_start_year, prefix),
  FOREIGN KEY (tenant_id, gst_registration_id) REFERENCES gst_registrations (tenant_id, id),
  CHECK (char_length(prefix) + pad_width <= 16)          -- GST: invoice number max 16 chars
);
-- Issuing picks "the" active series for a registration, type and year.
CREATE UNIQUE INDEX document_series_active_uq
  ON document_series (tenant_id, gst_registration_id, doc_type, fy_start_year) WHERE is_active;

CREATE TABLE documents (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                uuid NOT NULL REFERENCES tenants (id),
  doc_type                 text NOT NULL CHECK (doc_type IN ('QUOTATION', 'PROFORMA', 'TAX_INVOICE', 'BILL_OF_SUPPLY', 'CREDIT_NOTE', 'DEBIT_NOTE')),
  status                   text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ISSUED', 'ACCEPTED', 'DECLINED', 'CANCELLED')),
  gst_registration_id      uuid NOT NULL,
  series_id                uuid,
  doc_number               varchar(16) CHECK (doc_number ~ '^[A-Za-z0-9/-]{1,16}$'),
  doc_date                 date NOT NULL,
  fy_start_year            smallint GENERATED ALWAYS AS (fy_start_year(doc_date)) STORED,
  due_date                 date,
  valid_until              date,                          -- quotations
  party_id                 uuid NOT NULL,
  project_id               uuid,
  source_document_id       uuid,                          -- quotation/proforma this was converted from
  original_document_id     uuid,                          -- invoice a credit/debit note adjusts
  is_ra_bill               boolean NOT NULL DEFAULT false,
  ra_sequence              integer CHECK (ra_sequence > 0),
  -- Frozen copies taken at issue, so later edits to the party or our own
  -- registration never change an issued document.
  supplier_snapshot        jsonb,
  party_snapshot           jsonb,
  place_of_supply          char(2) NOT NULL CHECK (place_of_supply ~ '^[0-9]{2}$'),
  supply_type              text NOT NULL CHECK (supply_type IN ('INTRA_STATE', 'INTER_STATE')),
  reverse_charge           boolean NOT NULL DEFAULT false,   -- the recipient pays the tax
  -- SEZ: supply to an SEZ unit / developer (always inter-State, IGST Act s.7(5)(b));
  -- EXPORT: recipient outside India and no Indian site (place of supply 96).
  supply_category          text NOT NULL DEFAULT 'REGULAR' CHECK (supply_category IN ('REGULAR', 'SEZ', 'EXPORT')),
  lut                      boolean NOT NULL DEFAULT false,   -- zero-rated without IGST, under the registration's LUT
  -- Totals: computed by the tax engine on every draft save and verified
  -- against the lines when the document is issued (see documents_guard).
  subtotal                 numeric(14,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
  cgst_amount              numeric(14,2) NOT NULL DEFAULT 0 CHECK (cgst_amount >= 0),
  sgst_amount              numeric(14,2) NOT NULL DEFAULT 0 CHECK (sgst_amount >= 0),
  igst_amount              numeric(14,2) NOT NULL DEFAULT 0 CHECK (igst_amount >= 0),
  cess_amount              numeric(14,2) NOT NULL DEFAULT 0 CHECK (cess_amount >= 0),
  round_off                numeric(4,2) NOT NULL DEFAULT 0 CHECK (round_off BETWEEN -1 AND 1),
  round_to_rupee           boolean NOT NULL DEFAULT false,   -- recompute keeps the user's choice
  grand_total              numeric(14,2) NOT NULL DEFAULT 0,
  -- Construction deductions: they do not change the taxable value, they
  -- reduce what the client actually pays now.
  retention_amount         numeric(14,2) NOT NULL DEFAULT 0 CHECK (retention_amount >= 0),
  income_tax_tds_amount    numeric(14,2) NOT NULL DEFAULT 0 CHECK (income_tax_tds_amount >= 0),
  gst_tds_amount           numeric(14,2) NOT NULL DEFAULT 0 CHECK (gst_tds_amount >= 0),
  advance_recovery_amount  numeric(14,2) NOT NULL DEFAULT 0 CHECK (advance_recovery_amount >= 0),
  net_receivable           numeric(14,2) NOT NULL DEFAULT 0 CHECK (net_receivable >= 0),
  -- Maintained only by the allocations trigger; the CHECK below makes
  -- over-payment impossible even under concurrent requests.
  amount_settled           numeric(14,2) NOT NULL DEFAULT 0,
  is_gst_document          boolean GENERATED ALWAYS AS (doc_type IN ('TAX_INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE')) STORED,
  is_revenue               boolean GENERATED ALWAYS AS (doc_type NOT IN ('QUOTATION', 'PROFORMA')) STORED,
  notes                    text,
  terms                    text,
  pdf_attachment_id        uuid,
  issued_at                timestamptz,
  issued_by                uuid REFERENCES users (id),
  cancelled_at             timestamptz,
  cancelled_by             uuid REFERENCES users (id),
  cancel_reason            text,
  -- Approval (Part B): who asked, and the version of the draft an owner approved
  -- (an edit after it bumps the version, so the approval no longer holds).
  approval_requested_at    timestamptz,
  approval_requested_by    uuid REFERENCES users (id),
  approved_version         integer,
  approved_at              timestamptz,
  approved_by              uuid REFERENCES users (id),
  version                  integer NOT NULL DEFAULT 1,
  created_by               uuid NOT NULL REFERENCES users (id),
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),

  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, gst_registration_id) REFERENCES gst_registrations (tenant_id, id),
  FOREIGN KEY (tenant_id, series_id)            REFERENCES document_series (tenant_id, id),
  FOREIGN KEY (tenant_id, party_id)             REFERENCES parties (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id)           REFERENCES projects (tenant_id, id),
  FOREIGN KEY (tenant_id, source_document_id)   REFERENCES documents (tenant_id, id),
  FOREIGN KEY (tenant_id, original_document_id) REFERENCES documents (tenant_id, id),
  FOREIGN KEY (tenant_id, pdf_attachment_id)    REFERENCES attachments (tenant_id, id),

  -- anything past DRAFT must be fully numbered and snapshotted
  CHECK (status = 'DRAFT' OR (doc_number IS NOT NULL AND series_id IS NOT NULL AND issued_at IS NOT NULL
                              AND issued_by IS NOT NULL AND supplier_snapshot IS NOT NULL AND party_snapshot IS NOT NULL)),
  CHECK (status <> 'DRAFT' OR doc_number IS NULL),       -- numbers are assigned at issue, never on drafts
  CHECK (status NOT IN ('ACCEPTED', 'DECLINED') OR doc_type = 'QUOTATION'),
  CHECK (status <> 'CANCELLED' OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND amount_settled = 0)),
  CHECK (original_document_id IS NULL OR doc_type IN ('CREDIT_NOTE', 'DEBIT_NOTE')),
  CHECK (is_ra_bill = (ra_sequence IS NOT NULL)),
  CHECK (NOT is_ra_bill OR (doc_type IN ('PROFORMA', 'TAX_INVOICE', 'BILL_OF_SUPPLY') AND project_id IS NOT NULL)),
  -- tax arithmetic
  CHECK (cgst_amount = sgst_amount),
  CHECK (supply_type = 'INTRA_STATE' OR (cgst_amount = 0 AND sgst_amount = 0)),
  CHECK (supply_type = 'INTER_STATE' OR igst_amount = 0),
  CHECK (doc_type <> 'BILL_OF_SUPPLY' OR (cgst_amount = 0 AND igst_amount = 0 AND cess_amount = 0)),
  CHECK (supply_category = 'REGULAR' OR supply_type = 'INTER_STATE'),
  CHECK (supply_category <> 'EXPORT' OR place_of_supply = '96'),
  CHECK (NOT lut OR (supply_category IN ('SEZ', 'EXPORT') AND igst_amount = 0 AND cgst_amount = 0 AND cess_amount = 0)),
  CHECK (NOT reverse_charge OR (supply_category = 'REGULAR' AND doc_type IN ('TAX_INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE'))),
  -- under reverse charge the tax is shown but the recipient pays it: not in the total
  CHECK (grand_total = subtotal + CASE WHEN reverse_charge THEN 0 ELSE cgst_amount + sgst_amount + igst_amount + cess_amount END + round_off),
  CHECK (net_receivable = grand_total - retention_amount - income_tax_tds_amount - gst_tds_amount - advance_recovery_amount),
  CHECK (amount_settled >= 0 AND amount_settled <= net_receivable),
  CHECK (due_date IS NULL OR due_date >= doc_date),
  CHECK ((approved_version IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_by IS NULL))
);

-- GST: numbers unique per registration (GSTIN) per financial year.
CREATE UNIQUE INDEX documents_number_uq
  ON documents (tenant_id, gst_registration_id, fy_start_year, doc_number) WHERE doc_number IS NOT NULL;
CREATE UNIQUE INDEX documents_ra_sequence_uq
  ON documents (tenant_id, project_id, doc_type, ra_sequence) WHERE is_ra_bill AND status <> 'CANCELLED';
CREATE INDEX documents_date_idx     ON documents (tenant_id, doc_date DESC);
CREATE INDEX documents_party_idx    ON documents (tenant_id, party_id, doc_date DESC);
CREATE INDEX documents_project_idx  ON documents (tenant_id, project_id, doc_date DESC) WHERE project_id IS NOT NULL;
CREATE INDEX documents_type_idx     ON documents (tenant_id, doc_type, status);
CREATE INDEX documents_open_idx     ON documents (tenant_id, due_date)
  WHERE status = 'ISSUED' AND is_revenue AND amount_settled < net_receivable;
CREATE INDEX documents_number_trgm_idx ON documents USING gin (doc_number gin_trgm_ops) WHERE doc_number IS NOT NULL;

CREATE TABLE document_lines (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants (id),
  document_id          uuid NOT NULL,
  line_no              smallint NOT NULL CHECK (line_no > 0),
  catalog_item_id      uuid,
  catalog_variant_id   uuid,                                -- W.4: a variant of catalog_item_id
  boq_item_id          uuid,
  description          text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 2000),
  sac_hsn              text CHECK (sac_hsn ~ '^[0-9]{4,8}$'),
  unit                 text,
  quantity             numeric(14,3) NOT NULL CHECK (quantity > 0),       -- RA bill: quantity in THIS bill
  prev_cumulative_qty  numeric(14,3) CHECK (prev_cumulative_qty >= 0),    -- RA bill: billed up to the previous bill (snapshot)
  rate                 numeric(14,2) NOT NULL CHECK (rate >= 0),
  discount_amount      numeric(14,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
  discount_pct         numeric(5,2) CHECK (discount_pct BETWEEN 0 AND 100),  -- B.5: discount as %; the amount is worked out from it
  taxable_value        numeric(14,2) NOT NULL CHECK (taxable_value >= 0),
  gst_rate             numeric(5,2) NOT NULL DEFAULT 0 CHECK (gst_rate BETWEEN 0 AND 50),
  cgst_amount          numeric(14,2) NOT NULL DEFAULT 0 CHECK (cgst_amount >= 0),
  sgst_amount          numeric(14,2) NOT NULL DEFAULT 0 CHECK (sgst_amount >= 0),
  igst_amount          numeric(14,2) NOT NULL DEFAULT 0 CHECK (igst_amount >= 0),
  cess_amount          numeric(14,2) NOT NULL DEFAULT 0 CHECK (cess_amount >= 0),
  line_total           numeric(14,2) NOT NULL,
  UNIQUE (tenant_id, id),
  UNIQUE (document_id, line_no),
  FOREIGN KEY (tenant_id, document_id)     REFERENCES documents (tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, catalog_item_id) REFERENCES catalog_items (tenant_id, id),
  FOREIGN KEY (tenant_id, catalog_item_id, catalog_variant_id)
    REFERENCES catalog_item_variants (tenant_id, catalog_item_id, id),
  FOREIGN KEY (tenant_id, boq_item_id)     REFERENCES boq_items (tenant_id, id),
  CHECK (catalog_variant_id IS NULL OR catalog_item_id IS NOT NULL),
  CHECK (taxable_value = round(quantity * rate, 2) - discount_amount),
  CHECK (cgst_amount = sgst_amount),
  CHECK (line_total = taxable_value + cgst_amount + sgst_amount + igst_amount + cess_amount)
);
CREATE INDEX document_lines_boq_idx ON document_lines (tenant_id, boq_item_id) WHERE boq_item_id IS NOT NULL;
-- An item's last use and the rate last charged to a client (B.1, B.8).
CREATE INDEX document_lines_catalog_idx ON document_lines (tenant_id, catalog_item_id) WHERE catalog_item_id IS NOT NULL;

-- Measurement sheets (B.9): how a line's quantity was measured. Each row is
-- number x length x breadth x height (empty sizes count as 1), rounded half up
-- to 3 decimals; a deduct row (an opening) takes its quantity off. The line's
-- quantity is the total. Rows go with their line (cascade) and, like lines,
-- change only while the bill is a draft (document_lines_guard, section 7b).
CREATE TABLE document_line_measurements (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants (id),
  document_id  uuid NOT NULL,
  line_id      uuid NOT NULL,
  row_no       smallint NOT NULL CHECK (row_no > 0),
  description  text CHECK (char_length(description) <= 500),
  nos          numeric(14,3) NOT NULL DEFAULT 1 CHECK (nos > 0),
  length       numeric(14,3) CHECK (length > 0),
  breadth      numeric(14,3) CHECK (breadth > 0),
  height       numeric(14,3) CHECK (height > 0),
  deduct       boolean NOT NULL DEFAULT false,
  quantity     numeric(14,3) NOT NULL CHECK (quantity > 0),
  UNIQUE (line_id, row_no),
  FOREIGN KEY (tenant_id, document_id) REFERENCES documents (tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, line_id)     REFERENCES document_lines (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX line_measurements_line_idx ON document_line_measurements (tenant_id, line_id);

-- =============================================================================
-- 5. Money in: payments and allocations
--    (Payables / vendor bills are a later phase; expenses track their own
--    payment for now.)
-- =============================================================================

CREATE TABLE payments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants (id),
  party_id      uuid NOT NULL,
  project_id    uuid,
  payment_date  date NOT NULL,
  amount        numeric(14,2) NOT NULL CHECK (amount > 0),
  mode          text NOT NULL CHECK (mode IN ('BANK_TRANSFER', 'UPI', 'CHEQUE', 'CASH', 'CARD', 'OTHER')),
  reference     text CHECK (char_length(reference) <= 100),   -- UTR / cheque number
  notes         text,
  status        text NOT NULL DEFAULT 'RECORDED' CHECK (status IN ('RECORDED', 'VOIDED')),
  voided_at     timestamptz,
  voided_by     uuid REFERENCES users (id),
  void_reason   text,
  version       integer NOT NULL DEFAULT 1,
  created_by    uuid NOT NULL REFERENCES users (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, party_id)   REFERENCES parties (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id),
  CHECK (status <> 'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL))
);
CREATE INDEX payments_party_idx ON payments (tenant_id, party_id, payment_date DESC);
CREATE INDEX payments_date_idx  ON payments (tenant_id, payment_date DESC);

-- Retention money the client now releases. The retention was part of the
-- invoices' value (GST was charged then), so a release is not a new supply
-- and not a tax document: only money now due, collected through allocations
-- like an invoice. At most the retention still held per project and book
-- (issued tax invoices = GST, bills of supply = NON_GST) can be released.
CREATE TABLE retention_releases (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants (id),
  project_id      uuid NOT NULL,
  party_id        uuid NOT NULL,                     -- the project's client
  book            text NOT NULL CHECK (book IN ('GST', 'NON_GST')),
  release_date    date NOT NULL,
  due_date        date,
  amount          numeric(14,2) NOT NULL CHECK (amount > 0),
  -- Maintained only by the allocations trigger, like documents.amount_settled.
  amount_settled  numeric(14,2) NOT NULL DEFAULT 0,
  reference       text CHECK (char_length(reference) <= 50),
  notes           text CHECK (char_length(notes) <= 2000),
  status          text NOT NULL DEFAULT 'RELEASED' CHECK (status IN ('RELEASED', 'CANCELLED')),
  cancelled_at    timestamptz,
  cancelled_by    uuid REFERENCES users (id),
  cancel_reason   text,
  version         integer NOT NULL DEFAULT 1,
  created_by      uuid NOT NULL REFERENCES users (id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id),
  FOREIGN KEY (tenant_id, party_id)   REFERENCES parties (tenant_id, id),
  CHECK (amount_settled >= 0 AND amount_settled <= amount),
  CHECK (status <> 'CANCELLED' OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND amount_settled = 0)),
  CHECK (due_date IS NULL OR due_date >= release_date)
);
CREATE INDEX retention_releases_project_idx ON retention_releases (tenant_id, project_id, release_date DESC);

-- Settles a document from either a payment or an issued credit note, or a
-- retention release from a payment.
CREATE TABLE allocations (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenants (id),
  document_id           uuid,                      -- the invoice / debit note being settled
  retention_release_id  uuid,                      -- or the retention release
  payment_id            uuid,
  credit_note_id        uuid,
  amount                numeric(14,2) NOT NULL CHECK (amount > 0),
  created_by            uuid NOT NULL REFERENCES users (id),
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, document_id)          REFERENCES documents (tenant_id, id),
  FOREIGN KEY (tenant_id, retention_release_id) REFERENCES retention_releases (tenant_id, id),
  FOREIGN KEY (tenant_id, payment_id)           REFERENCES payments (tenant_id, id),
  FOREIGN KEY (tenant_id, credit_note_id)       REFERENCES documents (tenant_id, id),
  CHECK (num_nonnulls(payment_id, credit_note_id) = 1),
  CHECK (num_nonnulls(document_id, retention_release_id) = 1),
  CHECK (retention_release_id IS NULL OR payment_id IS NOT NULL)   -- releases: payments only
);
CREATE UNIQUE INDEX allocations_payment_uq ON allocations (document_id, payment_id)     WHERE payment_id IS NOT NULL;
CREATE UNIQUE INDEX allocations_cn_uq      ON allocations (document_id, credit_note_id) WHERE credit_note_id IS NOT NULL;
CREATE UNIQUE INDEX allocations_release_uq ON allocations (retention_release_id, payment_id) WHERE retention_release_id IS NOT NULL;
CREATE INDEX allocations_payment_idx ON allocations (tenant_id, payment_id);

CREATE TABLE expenses (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants (id),
  project_id          uuid,
  vendor_party_id     uuid,
  category            text NOT NULL CHECK (category IN ('MATERIAL', 'LABOUR', 'SUBCONTRACT', 'EQUIPMENT', 'TRANSPORT', 'SITE_OVERHEAD', 'OFFICE', 'OTHER')),
  expense_date        date NOT NULL,
  description         text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 1000),
  vendor_bill_number  text CHECK (char_length(vendor_bill_number) <= 50),
  taxable_value       numeric(14,2) NOT NULL CHECK (taxable_value >= 0),
  gst_amount          numeric(14,2) NOT NULL DEFAULT 0 CHECK (gst_amount >= 0),
  total_amount        numeric(14,2) NOT NULL,
  itc_eligible        boolean NOT NULL DEFAULT false,
  amount_paid         numeric(14,2) NOT NULL DEFAULT 0,
  payment_mode        text CHECK (payment_mode IN ('BANK_TRANSFER', 'UPI', 'CHEQUE', 'CASH', 'CARD', 'OTHER')),
  attachment_id       uuid,
  status              text NOT NULL DEFAULT 'RECORDED' CHECK (status IN ('RECORDED', 'VOIDED')),
  version             integer NOT NULL DEFAULT 1,
  created_by          uuid NOT NULL REFERENCES users (id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id)      REFERENCES projects (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_party_id) REFERENCES parties (tenant_id, id),
  FOREIGN KEY (tenant_id, attachment_id)   REFERENCES attachments (tenant_id, id),
  CHECK (total_amount = taxable_value + gst_amount),
  CHECK (amount_paid >= 0 AND amount_paid <= total_amount)
);
CREATE INDEX expenses_project_idx ON expenses (tenant_id, project_id, expense_date DESC);
CREATE INDEX expenses_date_idx    ON expenses (tenant_id, expense_date DESC);

-- Payables (Part B): what we owe vendors and subcontractors. A vendor bill is
-- their bill as we received it; the TDS we deduct (s.194C...) comes off what
-- we pay (net_payable); payments out are set against bills by vendor
-- allocations, which keep vendor_bills.amount_paid in step (7d). Small spends
-- stay expenses.
-- Subcontract work orders (Part B, payables part 2): the work let to a
-- subcontractor on one project, item by item at agreed rates. Its items are
-- a separate list from the client's BOQ (often a subset at other rates),
-- linked to a BOQ item when there is one. RA bills received are vendor bills
-- with work_order_id set and lines against these items (7e).
CREATE TABLE work_orders (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  project_id       uuid NOT NULL,
  vendor_party_id  uuid NOT NULL,
  wo_number        text NOT NULL CHECK (char_length(wo_number) BETWEEN 1 AND 30),   -- ours
  wo_date          date NOT NULL,
  title            text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
  terms            text CHECK (char_length(terms) <= 4000),
  retention_pct    numeric(5,2) NOT NULL DEFAULT 0 CHECK (retention_pct >= 0 AND retention_pct <= 20),
  tds_section      text CHECK (tds_section ~ '^19[0-9]{1,2}[A-Z]{0,3}$'),
  tds_rate         numeric(5,2) NOT NULL DEFAULT 0 CHECK (tds_rate >= 0 AND tds_rate <= 30),
  status           text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
  version          integer NOT NULL DEFAULT 1,
  created_by       uuid NOT NULL REFERENCES users (id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id)      REFERENCES projects (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_party_id) REFERENCES parties (tenant_id, id),
  CHECK (tds_section IS NOT NULL OR tds_rate = 0)
);
CREATE UNIQUE INDEX work_orders_number_uq ON work_orders (tenant_id, lower(wo_number));
CREATE INDEX work_orders_project_idx ON work_orders (tenant_id, project_id);
CREATE INDEX work_orders_vendor_idx  ON work_orders (tenant_id, vendor_party_id);

CREATE TABLE work_order_items (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants (id),
  work_order_id  uuid NOT NULL,
  boq_item_id    uuid,                                   -- the client's BOQ item, when there is one
  item_code      text NOT NULL CHECK (char_length(item_code) BETWEEN 1 AND 30),
  description    text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 2000),
  unit           text NOT NULL CHECK (char_length(unit) BETWEEN 1 AND 20),
  sac_hsn        text CHECK (sac_hsn ~ '^[0-9]{4,8}$'),
  qty            numeric(14,3) NOT NULL CHECK (qty > 0),  -- agreed; RA bills never go past it (7e)
  rate           numeric(14,2) NOT NULL CHECK (rate >= 0),
  gst_rate       numeric(5,2) NOT NULL DEFAULT 18 CHECK (gst_rate BETWEEN 0 AND 50),
  sort_order     integer NOT NULL DEFAULT 0,
  version        integer NOT NULL DEFAULT 1,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, work_order_id, item_code),
  FOREIGN KEY (tenant_id, work_order_id) REFERENCES work_orders (tenant_id, id),
  FOREIGN KEY (tenant_id, boq_item_id)   REFERENCES boq_items (tenant_id, id)
);


CREATE TABLE vendor_bills (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  vendor_party_id  uuid NOT NULL,
  project_id       uuid,
  bill_number      text NOT NULL CHECK (char_length(bill_number) BETWEEN 1 AND 50),   -- the vendor's own number
  bill_date        date NOT NULL,
  due_date         date,
  category         text NOT NULL CHECK (category IN ('MATERIAL', 'LABOUR', 'SUBCONTRACT', 'EQUIPMENT', 'TRANSPORT', 'SITE_OVERHEAD', 'OFFICE', 'OTHER')),
  description      text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 1000),
  taxable_value    numeric(14,2) NOT NULL CHECK (taxable_value >= 0),
  gst_amount       numeric(14,2) NOT NULL DEFAULT 0 CHECK (gst_amount >= 0),
  total_amount     numeric(14,2) NOT NULL,
  itc_eligible     boolean NOT NULL DEFAULT false,
  tds_section      text CHECK (tds_section ~ '^19[0-9]{1,2}[A-Z]{0,3}$'),
  tds_rate         numeric(5,2) NOT NULL DEFAULT 0 CHECK (tds_rate >= 0 AND tds_rate <= 30),
  tds_amount       numeric(14,2) NOT NULL DEFAULT 0 CHECK (tds_amount >= 0),
  net_payable      numeric(14,2) NOT NULL,
  -- RA bills against a subcontract work order (Part B, payables part 2; 7e).
  work_order_id    uuid,
  ra_number        integer CHECK (ra_number > 0),
  retention_amount numeric(14,2) NOT NULL DEFAULT 0 CHECK (retention_amount >= 0),  -- held back
  -- Maintained only by the vendor allocations trigger, like documents.amount_settled.
  amount_paid      numeric(14,2) NOT NULL DEFAULT 0,
  attachment_id    uuid,
  notes            text CHECK (char_length(notes) <= 2000),
  status           text NOT NULL DEFAULT 'RECORDED' CHECK (status IN ('RECORDED', 'VOIDED')),
  voided_at        timestamptz,
  voided_by        uuid REFERENCES users (id),
  void_reason      text,
  version          integer NOT NULL DEFAULT 1,
  created_by       uuid NOT NULL REFERENCES users (id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_party_id) REFERENCES parties (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id)      REFERENCES projects (tenant_id, id),
  FOREIGN KEY (tenant_id, attachment_id)   REFERENCES attachments (tenant_id, id),
  FOREIGN KEY (tenant_id, work_order_id)   REFERENCES work_orders (tenant_id, id),
  CHECK (due_date IS NULL OR due_date >= bill_date),
  CHECK (total_amount = taxable_value + gst_amount),
  CHECK (tds_section IS NOT NULL OR (tds_rate = 0 AND tds_amount = 0)),
  CHECK (tds_amount <= taxable_value),                      -- TDS is on the value before GST
  CHECK (net_payable = total_amount - tds_amount - retention_amount),
  CHECK (retention_amount <= taxable_value),
  CHECK ((work_order_id IS NULL) = (ra_number IS NULL)),
  CHECK (amount_paid >= 0 AND amount_paid <= net_payable),
  CHECK (status <> 'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND amount_paid = 0))
);
-- A vendor's bill number is entered once (a voided bill may be entered again).
CREATE UNIQUE INDEX vendor_bills_number_uq ON vendor_bills (tenant_id, vendor_party_id, lower(bill_number))
  WHERE status = 'RECORDED';
CREATE INDEX vendor_bills_vendor_idx  ON vendor_bills (tenant_id, vendor_party_id, bill_date DESC);
CREATE INDEX vendor_bills_date_idx    ON vendor_bills (tenant_id, bill_date DESC);
CREATE INDEX vendor_bills_project_idx ON vendor_bills (tenant_id, project_id, bill_date DESC);
CREATE INDEX vendor_bills_work_order_idx ON vendor_bills (tenant_id, work_order_id, ra_number)
  WHERE work_order_id IS NOT NULL;
-- One RA bill of each number per work order (a voided one may be entered again).
CREATE UNIQUE INDEX vendor_bills_ra_uq ON vendor_bills (tenant_id, work_order_id, ra_number)
  WHERE status = 'RECORDED' AND work_order_id IS NOT NULL;

-- Retention released to a subcontractor (payables part 2): part of what was
-- held back on a work order's RA bills, now owed to them. Paid like a vendor
-- bill (vendor_allocations); never more than is still held (7e).
CREATE TABLE vendor_retention_releases (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  work_order_id    uuid NOT NULL,
  vendor_party_id  uuid NOT NULL,                     -- the work order's subcontractor
  release_date     date NOT NULL,
  due_date         date,
  amount           numeric(14,2) NOT NULL CHECK (amount > 0),
  -- Maintained only by the vendor allocations trigger, like vendor_bills.amount_paid.
  amount_paid      numeric(14,2) NOT NULL DEFAULT 0,
  reference        text CHECK (char_length(reference) <= 50),
  notes            text CHECK (char_length(notes) <= 2000),
  status           text NOT NULL DEFAULT 'RELEASED' CHECK (status IN ('RELEASED', 'CANCELLED')),
  cancelled_at     timestamptz,
  cancelled_by     uuid REFERENCES users (id),
  cancel_reason    text,
  version          integer NOT NULL DEFAULT 1,
  created_by       uuid NOT NULL REFERENCES users (id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, work_order_id)   REFERENCES work_orders (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_party_id) REFERENCES parties (tenant_id, id),
  CHECK (amount_paid >= 0 AND amount_paid <= amount),
  CHECK (status <> 'CANCELLED' OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND amount_paid = 0)),
  CHECK (due_date IS NULL OR due_date >= release_date)
);
CREATE INDEX vendor_retention_releases_wo_idx ON vendor_retention_releases (tenant_id, work_order_id);
CREATE INDEX vendor_retention_releases_vendor_idx ON vendor_retention_releases (tenant_id, vendor_party_id, release_date DESC);

CREATE TABLE vendor_payments (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  vendor_party_id  uuid NOT NULL,
  project_id       uuid,
  payment_date     date NOT NULL,
  amount           numeric(14,2) NOT NULL CHECK (amount > 0),
  mode             text NOT NULL CHECK (mode IN ('BANK_TRANSFER', 'UPI', 'CHEQUE', 'CASH', 'CARD', 'OTHER')),
  reference        text CHECK (char_length(reference) <= 100),   -- UTR / cheque number
  notes            text CHECK (char_length(notes) <= 2000),
  status           text NOT NULL DEFAULT 'RECORDED' CHECK (status IN ('RECORDED', 'VOIDED')),
  voided_at        timestamptz,
  voided_by        uuid REFERENCES users (id),
  void_reason      text,
  version          integer NOT NULL DEFAULT 1,
  created_by       uuid NOT NULL REFERENCES users (id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_party_id) REFERENCES parties (tenant_id, id),
  FOREIGN KEY (tenant_id, project_id)      REFERENCES projects (tenant_id, id),
  CHECK (status <> 'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL))
);
CREATE INDEX vendor_payments_vendor_idx ON vendor_payments (tenant_id, vendor_party_id, payment_date DESC);
CREATE INDEX vendor_payments_date_idx   ON vendor_payments (tenant_id, payment_date DESC);

CREATE TABLE vendor_allocations (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants (id),
  vendor_payment_id  uuid NOT NULL,
  vendor_bill_id     uuid,                      -- the bill being paid
  vendor_retention_release_id uuid,              -- or the retention released (payables part 2)
  amount             numeric(14,2) NOT NULL CHECK (amount > 0),
  created_by         uuid NOT NULL REFERENCES users (id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (vendor_bill_id, vendor_payment_id),
  FOREIGN KEY (tenant_id, vendor_payment_id) REFERENCES vendor_payments (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_bill_id)    REFERENCES vendor_bills (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_retention_release_id) REFERENCES vendor_retention_releases (tenant_id, id),
  CHECK (num_nonnulls(vendor_bill_id, vendor_retention_release_id) = 1)
);
CREATE UNIQUE INDEX vendor_allocations_release_uq ON vendor_allocations (vendor_retention_release_id, vendor_payment_id)
  WHERE vendor_retention_release_id IS NOT NULL;
CREATE INDEX vendor_allocations_payment_idx ON vendor_allocations (tenant_id, vendor_payment_id);

-- An RA bill's lines: this bill's quantity of each work order item, at the
-- rate of the work order when billed. Written once; an RA bill is edited by
-- replacing its lines while nothing is paid on it (7e).
CREATE TABLE vendor_bill_lines (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants (id),
  vendor_bill_id      uuid NOT NULL,
  work_order_item_id  uuid NOT NULL,
  qty                 numeric(14,3) NOT NULL CHECK (qty > 0),
  rate                numeric(14,2) NOT NULL CHECK (rate >= 0),
  amount              numeric(14,2) NOT NULL,
  gst_rate            numeric(5,2) NOT NULL CHECK (gst_rate BETWEEN 0 AND 50),
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (vendor_bill_id, work_order_item_id),
  FOREIGN KEY (tenant_id, vendor_bill_id)     REFERENCES vendor_bills (tenant_id, id),
  FOREIGN KEY (tenant_id, work_order_item_id) REFERENCES work_order_items (tenant_id, id),
  CHECK (amount = round(qty * rate, 2))
);
CREATE INDEX vendor_bill_lines_item_idx ON vendor_bill_lines (tenant_id, work_order_item_id);

-- Bank statements (Part B): lines imported from the bank's file, each matched
-- by a person to the payment (in) or payment to a vendor (out) it is, or
-- ignored (bank charges, transfers between own accounts). Nothing is
-- matched without someone confirming it.
CREATE TABLE bank_lines (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants (id),
  account_label      text NOT NULL CHECK (char_length(account_label) BETWEEN 1 AND 60),   -- "HDFC current 1234"
  line_date          date NOT NULL,
  narration          text NOT NULL CHECK (char_length(narration) <= 500),
  reference          text CHECK (char_length(reference) <= 100),   -- UTR / cheque number, as the bank prints it
  money_in           numeric(14,2) NOT NULL DEFAULT 0 CHECK (money_in >= 0),
  money_out          numeric(14,2) NOT NULL DEFAULT 0 CHECK (money_out >= 0),
  balance            numeric(16,2),
  fingerprint        text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),   -- the same line imported twice is skipped
  status             text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'MATCHED', 'IGNORED')),
  payment_id         uuid,
  vendor_payment_id  uuid,
  note               text CHECK (char_length(note) <= 200),
  version            integer NOT NULL DEFAULT 1,
  created_by         uuid NOT NULL REFERENCES users (id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, fingerprint),
  FOREIGN KEY (tenant_id, payment_id)        REFERENCES payments (tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_payment_id) REFERENCES vendor_payments (tenant_id, id),
  CHECK ((money_in > 0) <> (money_out > 0)),                       -- money in or money out
  CHECK (payment_id IS NULL OR money_in > 0),
  CHECK (vendor_payment_id IS NULL OR money_out > 0),
  CHECK (num_nonnulls(payment_id, vendor_payment_id) <= 1),
  CHECK ((status = 'MATCHED') = (num_nonnulls(payment_id, vendor_payment_id) = 1))
);
-- A payment is the money of one bank line at most.
CREATE UNIQUE INDEX bank_lines_payment_uq        ON bank_lines (payment_id)        WHERE payment_id IS NOT NULL;
CREATE UNIQUE INDEX bank_lines_vendor_payment_uq ON bank_lines (vendor_payment_id) WHERE vendor_payment_id IS NOT NULL;
CREATE INDEX bank_lines_status_idx ON bank_lines (tenant_id, status, line_date DESC);

-- GSTR-2B (Part B): the input tax credit statement the GST portal makes for a
-- registration and month, as uploaded (apps/gstr2b/reader.py). It is matched
-- against vendor bills and expenses when it is read, so the match follows the
-- books (apps/gstr2b/reconcile.py). Uploading a month again replaces it.
CREATE TABLE gstr2b_returns (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants (id),
  gst_registration_id  uuid NOT NULL,
  period               date NOT NULL CHECK (extract(day FROM period) = 1),   -- the month
  generated_on         date,
  file_name            text NOT NULL CHECK (char_length(file_name) BETWEEN 1 AND 255),
  doc_count            integer NOT NULL CHECK (doc_count >= 0),
  created_by           uuid NOT NULL REFERENCES users (id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, gst_registration_id, period),
  FOREIGN KEY (tenant_id, gst_registration_id) REFERENCES gst_registrations (tenant_id, id)
);

CREATE TABLE gstr2b_lines (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  return_id        uuid NOT NULL,
  section          text NOT NULL CHECK (section IN ('B2B', 'B2BA', 'CDNR', 'CDNRA')),
  doc_type         text NOT NULL CHECK (doc_type IN ('INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE')),
  supplier_gstin   varchar(15) NOT NULL,
  supplier_name    text NOT NULL DEFAULT '',
  doc_number       text NOT NULL CHECK (char_length(doc_number) BETWEEN 1 AND 50),
  original_number  text,                                -- amendments: the number amended
  doc_date         date NOT NULL,
  taxable_value    numeric(14,2) NOT NULL,
  igst             numeric(14,2) NOT NULL DEFAULT 0,
  cgst             numeric(14,2) NOT NULL DEFAULT 0,
  sgst             numeric(14,2) NOT NULL DEFAULT 0,
  cess             numeric(14,2) NOT NULL DEFAULT 0,
  place_of_supply  char(2),
  reverse_charge   boolean NOT NULL DEFAULT false,
  itc_available    boolean NOT NULL DEFAULT true,
  itc_reason       text,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, return_id) REFERENCES gstr2b_returns (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX gstr2b_lines_return_idx   ON gstr2b_lines (tenant_id, return_id);
CREATE INDEX gstr2b_lines_supplier_idx ON gstr2b_lines (tenant_id, supplier_gstin);

-- Notifications (Part B): the few events worth a look, one row per person
-- they are for (apps/notifications). Each person reads and marks only their
-- own (the own_rows policies); anyone in the business may be sent one.
-- dedupe_key makes an event land once per person (a daily job run twice adds
-- nothing).
CREATE TABLE notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants (id),
  user_id     uuid NOT NULL REFERENCES users (id),
  kind        text NOT NULL CHECK (kind IN ('QUOTATION_ACCEPTED', 'QUOTATION_DECLINED', 'BILLS_OVERDUE',
                                            'PAYABLES_DUE', 'MEMBER_JOINED', 'APPROVAL_REQUESTED',
                                            'BILL_APPROVED')),
  title       text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
  body        text CHECK (char_length(body) <= 1000),
  link        text CHECK (link ~ '^/([^/]|$)' AND char_length(link) <= 300),   -- a page of the app (not //)
  dedupe_key  text NOT NULL CHECK (char_length(dedupe_key) BETWEEN 1 AND 200),
  read_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, user_id, dedupe_key)
);
CREATE INDEX notifications_user_idx ON notifications (tenant_id, user_id, created_at DESC);

-- Site diary (Part B): what happened on a project each day, with photos
-- (uploaded attachments, images only). One entry per project and day, kept
-- by whoever is on site; photos can later be shown with an RA bill as proof
-- of work.
CREATE TABLE site_diary_entries (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants (id),
  project_id   uuid NOT NULL,
  entry_date   date NOT NULL,
  weather      text CHECK (weather IN ('SUNNY', 'CLOUDY', 'RAIN', 'HEAVY_RAIN')),
  workers      integer CHECK (workers >= 0 AND workers <= 10000),   -- on site that day
  work_done    text NOT NULL CHECK (char_length(work_done) BETWEEN 1 AND 4000),
  hold_ups     text CHECK (char_length(hold_ups) <= 2000),           -- what stopped or slowed work
  version      integer NOT NULL DEFAULT 1,
  created_by   uuid NOT NULL REFERENCES users (id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, project_id, entry_date),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)
);
CREATE INDEX site_diary_entries_project_idx ON site_diary_entries (tenant_id, project_id, entry_date DESC);

CREATE TABLE site_diary_photos (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants (id),
  entry_id       uuid NOT NULL,
  attachment_id  uuid NOT NULL,
  caption        text CHECK (char_length(caption) <= 200),
  sort_order     integer NOT NULL DEFAULT 0,
  created_by     uuid NOT NULL REFERENCES users (id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (entry_id, attachment_id),
  FOREIGN KEY (tenant_id, entry_id)      REFERENCES site_diary_entries (tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, attachment_id) REFERENCES attachments (tenant_id, id)
);
CREATE INDEX site_diary_photos_entry_idx ON site_diary_photos (tenant_id, entry_id, sort_order);

-- Proof of work (Part B): site diary photos chosen to go with a bill (an RA
-- bill, usually), shown with it in the client portal. Only photos of the
-- bill's project (7e).
CREATE TABLE document_photos (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants (id),
  document_id     uuid NOT NULL,
  diary_photo_id  uuid NOT NULL,
  sort_order      integer NOT NULL DEFAULT 0,
  created_by      uuid NOT NULL REFERENCES users (id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (document_id, diary_photo_id),
  FOREIGN KEY (tenant_id, document_id)    REFERENCES documents (tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, diary_photo_id) REFERENCES site_diary_photos (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX document_photos_document_idx ON document_photos (tenant_id, document_id, sort_order);

-- Income-tax TDS certificates (Form 16A) received from clients, to reconcile
-- with the TDS deducted on our bills. A record of the client's paper, not a
-- posting of ours: it may be corrected or deleted (audited).
CREATE TABLE tds_certificates (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants (id),
  party_id            uuid NOT NULL,                       -- the deductor (our client)
  deductor_tan        text NOT NULL CHECK (deductor_tan ~ '^[A-Z]{4}[0-9]{5}[A-Z]$'),
  section             text NOT NULL DEFAULT '194C' CHECK (section ~ '^19[0-9]{1,2}[A-Z]{0,3}$'),
  fy_start_year       smallint NOT NULL CHECK (fy_start_year BETWEEN 2000 AND 2100),
  quarter             smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  certificate_number  text NOT NULL CHECK (certificate_number ~ '^[A-Za-z0-9/-]{1,20}$'),
  certificate_date    date,
  amount_credited     numeric(14,2) CHECK (amount_credited >= 0),   -- as the certificate states
  tds_amount          numeric(14,2) NOT NULL CHECK (tds_amount >= 0),
  notes               text CHECK (char_length(notes) <= 2000),
  version             integer NOT NULL DEFAULT 1,
  created_by          uuid NOT NULL REFERENCES users (id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, deductor_tan, certificate_number),
  FOREIGN KEY (tenant_id, party_id) REFERENCES parties (tenant_id, id)
);
CREATE INDEX tds_certificates_party_idx ON tds_certificates (tenant_id, party_id, fy_start_year, quarter);

-- Payment reminders emailed to a client about an unpaid bill (W.2): a log,
-- append-only. The daily job sends each stage at most once per bill (the
-- partial unique index); MANUAL ones are sent by a member from the bill.
CREATE TABLE payment_reminders (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants (id),
  document_id  uuid NOT NULL,
  stage        text NOT NULL CHECK (stage IN ('BEFORE_DUE', 'ON_DUE', 'OVERDUE_7', 'OVERDUE_15',
                                              'OVERDUE_30', 'MANUAL')),
  sent_to      citext NOT NULL CHECK (char_length(sent_to) BETWEEN 3 AND 254),
  amount_due   numeric(14,2) NOT NULL CHECK (amount_due > 0),
  sent_by      uuid REFERENCES users (id),               -- NULL: the daily job
  sent_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, document_id) REFERENCES documents (tenant_id, id),
  CHECK ((stage = 'MANUAL') = (sent_by IS NOT NULL))
);
CREATE UNIQUE INDEX payment_reminders_stage_once ON payment_reminders (tenant_id, document_id, stage)
  WHERE NOT (stage = 'MANUAL');
CREATE INDEX payment_reminders_document_idx ON payment_reminders (tenant_id, document_id, sent_at DESC);

-- A bill emailed to its client with the PDF attached (B.15). A log: written once.
CREATE TABLE document_emails (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants (id),
  document_id  uuid NOT NULL,
  sent_to      citext NOT NULL CHECK (char_length(sent_to) BETWEEN 3 AND 254),
  copy         text NOT NULL CHECK (copy IN ('original', 'duplicate', 'triplicate')),
  sent_by      uuid NOT NULL REFERENCES users (id),
  sent_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, document_id) REFERENCES documents (tenant_id, id)
);
CREATE INDEX document_emails_doc_idx ON document_emails (tenant_id, document_id, sent_at DESC);

-- =============================================================================
-- 6. Infrastructure tables
-- =============================================================================

-- Makes POST retries safe: same key + same body → stored response is replayed.
CREATE TABLE idempotency_keys (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants (id),
  user_id          uuid NOT NULL REFERENCES users (id),
  key              text NOT NULL CHECK (char_length(key) BETWEEN 16 AND 100),
  request_method   text NOT NULL,
  request_path     text NOT NULL,
  request_hash     bytea NOT NULL CHECK (octet_length(request_hash) = 32),
  state            text NOT NULL DEFAULT 'IN_PROGRESS' CHECK (state IN ('IN_PROGRESS', 'COMPLETED')),
  response_status  smallint,
  response_body    jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL DEFAULT now() + interval '24 hours',
  UNIQUE (tenant_id, user_id, key)
);
CREATE INDEX idempotency_keys_expiry_idx ON idempotency_keys (expires_at);

-- Files exported for the user (CSV / XLSX registers, GSTR-1 JSON), written by
-- a background job. The file lives in object storage; rows and files are
-- purged after 7 days (they hold the business's figures).
CREATE TABLE exports (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants (id),
  kind          text NOT NULL CHECK (kind IN ('DOCUMENTS', 'PAYMENTS', 'EXPENSES', 'RECEIVABLES', 'GSTR1',
                                              'BOQ', 'PROJECTS', 'STATEMENT', 'TALLY', 'TDS_DEDUCTED')),
  format        text NOT NULL CHECK (format IN ('CSV', 'XLSX', 'JSON', 'PDF', 'XML')),
  params        jsonb NOT NULL DEFAULT '{}',
  status        text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'READY', 'FAILED')),
  file_name     text CHECK (char_length(file_name) BETWEEN 1 AND 200),
  storage_key   text UNIQUE,
  size_bytes    bigint CHECK (size_bytes >= 0),
  row_count     integer CHECK (row_count >= 0),
  warnings      jsonb NOT NULL DEFAULT '[]',
  error         text CHECK (char_length(error) <= 1000),
  requested_by  uuid NOT NULL REFERENCES users (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  UNIQUE (tenant_id, id),
  CHECK ((status = 'READY') = (storage_key IS NOT NULL AND file_name IS NOT NULL AND size_bytes IS NOT NULL)),
  CHECK ((status = 'PENDING') = (finished_at IS NULL)),
  CHECK ((format = 'JSON') = (kind = 'GSTR1')),
  CONSTRAINT exports_pdf_check CHECK (format <> 'PDF' OR kind = 'STATEMENT'),  -- a statement of account
  CONSTRAINT exports_xml_check CHECK ((format = 'XML') = (kind = 'TALLY'))  -- vouchers for Tally (B.16)
);
CREATE INDEX exports_requested_idx ON exports (tenant_id, requested_by, created_at DESC);

-- Append-only audit trail, written by triggers (so it cannot be skipped by
-- application code) and never updatable or deletable by the app.
CREATE TABLE audit_log (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      uuid NOT NULL,
  occurred_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
  actor_user_id  uuid,
  request_id     text,
  action         text NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
  table_name     text NOT NULL,
  row_id         uuid NOT NULL,
  old_data       jsonb,
  new_data       jsonb
);
CREATE INDEX audit_log_row_idx    ON audit_log (tenant_id, table_name, row_id, occurred_at);
CREATE INDEX audit_log_tenant_idx ON audit_log (tenant_id, occurred_at DESC);
-- A bill's line changes (its history): lines are written afresh on every save,
-- so they are found by the bill they belong to.
CREATE INDEX audit_log_line_doc_idx ON audit_log
  (tenant_id, (COALESCE(new_data ->> 'document_id', old_data ->> 'document_id')))
  WHERE table_name = 'document_lines';

-- =============================================================================
-- 7. Integrity triggers
-- =============================================================================

-- 7a. Document lifecycle + immutability.
CREATE FUNCTION documents_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  -- the only columns that may change once a document has left DRAFT
  -- (generated columns are listed because NEW does not hold them yet in a BEFORE trigger)
  mutable_after_issue constant text[] := ARRAY[
    'status', 'amount_settled', 'pdf_attachment_id', 'cancelled_at', 'cancelled_by',
    'cancel_reason', 'updated_at', 'version', 'fy_start_year', 'is_gst_document', 'is_revenue'];
  reg        record;
  line_count integer;
  l_sub      numeric;
  l_cgst     numeric;
  l_sgst     numeric;
  l_igst     numeric;
  l_cess     numeric;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'DRAFT' THEN
      RAISE EXCEPTION 'document % is %: only drafts can be deleted, cancel it instead', OLD.id, OLD.status
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN OLD;
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'DRAFT' THEN
      RAISE EXCEPTION 'documents must be created as DRAFT' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;

  -- UPDATE
  IF OLD.status = 'DRAFT' THEN
    IF NEW.status NOT IN ('DRAFT', 'ISSUED') THEN
      RAISE EXCEPTION 'a draft can only be issued or deleted' USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.status = 'ISSUED' THEN
      -- Totals must equal the sum of the lines at the moment of issue.
      SELECT count(*), coalesce(sum(taxable_value), 0), coalesce(sum(cgst_amount), 0),
             coalesce(sum(sgst_amount), 0), coalesce(sum(igst_amount), 0), coalesce(sum(cess_amount), 0)
        INTO line_count, l_sub, l_cgst, l_sgst, l_igst, l_cess
        FROM document_lines WHERE document_id = NEW.id;
      IF line_count = 0 THEN
        RAISE EXCEPTION 'cannot issue document % with no lines', NEW.id USING ERRCODE = 'check_violation';
      END IF;
      IF (NEW.subtotal, NEW.cgst_amount, NEW.sgst_amount, NEW.igst_amount, NEW.cess_amount)
         IS DISTINCT FROM (l_sub, l_cgst, l_sgst, l_igst, l_cess) THEN
        RAISE EXCEPTION 'document % totals do not match its lines', NEW.id USING ERRCODE = 'check_violation';
      END IF;

      -- Document type must be legal for the issuing registration.
      SELECT registration_type, state_code, lut_fy_start_year INTO reg
        FROM gst_registrations WHERE id = NEW.gst_registration_id;
      IF reg.registration_type <> 'REGULAR' AND NEW.doc_type IN ('TAX_INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE') THEN
        RAISE EXCEPTION '% registration cannot issue %; use BILL_OF_SUPPLY', reg.registration_type, NEW.doc_type
          USING ERRCODE = 'check_violation';
      END IF;
      IF reg.registration_type = 'REGULAR'
         AND NEW.supply_type <> (CASE WHEN NEW.supply_category <> 'REGULAR' THEN 'INTER_STATE'
                                      WHEN NEW.place_of_supply = reg.state_code THEN 'INTRA_STATE'
                                      ELSE 'INTER_STATE' END) THEN
        RAISE EXCEPTION 'supply_type does not match place of supply %', NEW.place_of_supply
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.lut AND reg.lut_fy_start_year IS DISTINCT FROM fy_start_year(NEW.doc_date) THEN
        RAISE EXCEPTION 'no Letter of Undertaking for the financial year of %', NEW.doc_date
          USING ERRCODE = 'check_violation';
      END IF;
    END IF;
    RETURN NEW;
  END IF;

  -- OLD.status is ISSUED / ACCEPTED / DECLINED / CANCELLED: content is frozen.
  IF (to_jsonb(NEW) - mutable_after_issue) IS DISTINCT FROM (to_jsonb(OLD) - mutable_after_issue) THEN
    RAISE EXCEPTION 'document % is %: issued documents cannot be edited (issue a credit/debit note)', OLD.id, OLD.status
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status
     AND NOT (OLD.status = 'ISSUED' AND NEW.status IN ('CANCELLED', 'ACCEPTED', 'DECLINED')) THEN
    RAISE EXCEPTION 'illegal status change % -> %', OLD.status, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER documents_guard
  BEFORE INSERT OR UPDATE OR DELETE ON documents
  FOR EACH ROW EXECUTE FUNCTION documents_guard();

-- 7b. Lines can only change while their document is a draft. FOR SHARE waits
--     for a concurrent "issue" transaction and then sees its result.
CREATE FUNCTION document_lines_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  doc_status text;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    SELECT status INTO doc_status FROM documents WHERE id = OLD.document_id FOR SHARE;
    -- NULL means the parent is being deleted (cascade from a draft delete)
    IF doc_status IS NOT NULL AND doc_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'lines of a % document cannot be changed', doc_status USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    SELECT status INTO doc_status FROM documents WHERE id = NEW.document_id FOR SHARE;
    IF doc_status IS NOT NULL AND doc_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'lines of a % document cannot be changed', doc_status USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  RETURN OLD;
END $$;

CREATE TRIGGER document_lines_guard
  BEFORE INSERT OR UPDATE OR DELETE ON document_lines
  FOR EACH ROW EXECUTE FUNCTION document_lines_guard();
CREATE TRIGGER document_line_measurements_guard
  BEFORE INSERT OR UPDATE OR DELETE ON document_line_measurements
  FOR EACH ROW EXECUTE FUNCTION document_lines_guard();

-- 7c. Allocations keep documents.amount_settled in step. Updating the document
--     row locks it, so concurrent allocations serialize, and the CHECK
--     amount_settled <= net_receivable rejects any over-payment.
--     SECURITY DEFINER: the app role has no UPDATE right on amount_settled, so
--     this trigger is the only way it can change. RLS still applies (FORCE).
CREATE FUNCTION allocations_apply() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  target      record;
  src_total   numeric;
  src_used    numeric;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.document_id IS NOT NULL THEN
      UPDATE documents SET amount_settled = amount_settled - OLD.amount WHERE id = OLD.document_id;
    ELSE
      UPDATE retention_releases SET amount_settled = amount_settled - OLD.amount
       WHERE id = OLD.retention_release_id;
    END IF;
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'allocations are immutable; delete and re-create' USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.document_id IS NOT NULL THEN
    SELECT doc_type, status, party_id INTO target FROM documents WHERE id = NEW.document_id;
    IF target.status <> 'ISSUED' OR target.doc_type NOT IN ('TAX_INVOICE', 'BILL_OF_SUPPLY', 'DEBIT_NOTE') THEN
      RAISE EXCEPTION 'only issued invoices, bills of supply and debit notes can be settled'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSE
    SELECT status, party_id INTO target FROM retention_releases WHERE id = NEW.retention_release_id;
    IF target.status IS DISTINCT FROM 'RELEASED' THEN
      RAISE EXCEPTION 'only open retention releases can be settled' USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  IF NEW.payment_id IS NOT NULL THEN
    SELECT amount INTO src_total FROM payments
     WHERE id = NEW.payment_id AND status = 'RECORDED' AND party_id = target.party_id
       FOR UPDATE;
  ELSE
    SELECT grand_total INTO src_total FROM documents
     WHERE id = NEW.credit_note_id AND doc_type = 'CREDIT_NOTE' AND status = 'ISSUED' AND party_id = target.party_id
       FOR UPDATE;
  END IF;
  IF src_total IS NULL THEN
    RAISE EXCEPTION 'allocation source must be a recorded payment / issued credit note of the same party'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT coalesce(sum(amount), 0) INTO src_used FROM allocations
   WHERE (NEW.payment_id IS NOT NULL AND payment_id = NEW.payment_id)
      OR (NEW.credit_note_id IS NOT NULL AND credit_note_id = NEW.credit_note_id);
  IF src_used + NEW.amount > src_total THEN
    RAISE EXCEPTION 'allocation exceeds the unallocated amount of its source' USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.document_id IS NOT NULL THEN
    UPDATE documents SET amount_settled = amount_settled + NEW.amount WHERE id = NEW.document_id;
  ELSE
    UPDATE retention_releases SET amount_settled = amount_settled + NEW.amount
     WHERE id = NEW.retention_release_id;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER allocations_apply
  BEFORE INSERT OR UPDATE OR DELETE ON allocations
  FOR EACH ROW EXECUTE FUNCTION allocations_apply();

-- 7d. Vendor allocations keep vendor_bills.amount_paid (and a released
--     retention's amount_paid) in step, as 7c does for bills out: the row
--     lock serializes concurrent payments and the CHECK amount_paid <= what
--     is owed rejects paying twice over.
CREATE FUNCTION vendor_allocations_apply() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  target     record;
  src_total  numeric;
  src_used   numeric;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.vendor_bill_id IS NOT NULL THEN
      UPDATE vendor_bills SET amount_paid = amount_paid - OLD.amount WHERE id = OLD.vendor_bill_id;
    ELSE
      UPDATE vendor_retention_releases SET amount_paid = amount_paid - OLD.amount
       WHERE id = OLD.vendor_retention_release_id;
    END IF;
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'allocations are immutable; delete and re-create' USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.vendor_bill_id IS NOT NULL THEN
    SELECT status = 'RECORDED' AS payable, vendor_party_id INTO target
      FROM vendor_bills WHERE id = NEW.vendor_bill_id;
  ELSE
    SELECT status = 'RELEASED' AS payable, vendor_party_id INTO target
      FROM vendor_retention_releases WHERE id = NEW.vendor_retention_release_id;
  END IF;
  IF target.payable IS NOT TRUE THEN
    RAISE EXCEPTION 'only recorded vendor bills and released retention can be paid'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT amount INTO src_total FROM vendor_payments
   WHERE id = NEW.vendor_payment_id AND status = 'RECORDED' AND vendor_party_id = target.vendor_party_id
     FOR UPDATE;
  IF src_total IS NULL THEN
    RAISE EXCEPTION 'a vendor bill is paid only by a recorded payment to the same vendor'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT coalesce(sum(amount), 0) INTO src_used FROM vendor_allocations
   WHERE vendor_payment_id = NEW.vendor_payment_id;
  IF src_used + NEW.amount > src_total THEN
    RAISE EXCEPTION 'allocation exceeds the unallocated amount of its payment' USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.vendor_bill_id IS NOT NULL THEN
    UPDATE vendor_bills SET amount_paid = amount_paid + NEW.amount WHERE id = NEW.vendor_bill_id;
  ELSE
    UPDATE vendor_retention_releases SET amount_paid = amount_paid + NEW.amount
     WHERE id = NEW.vendor_retention_release_id;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER vendor_allocations_apply
  BEFORE INSERT OR UPDATE OR DELETE ON vendor_allocations
  FOR EACH ROW EXECUTE FUNCTION vendor_allocations_apply();

-- 7e. Subcontract RA bills (Part B). A vendor bill with a work order is from
-- that work order's subcontractor, for its project, and is entered only while
-- the work order is open. Its lines are items of that work order, and the
-- quantity billed on recorded bills never passes the agreed quantity (the
-- work order item is locked, so two bills at once cannot both slip through);
-- an item's quantity cannot be cut below what is billed. Lines change only
-- while their bill is recorded and unpaid. That an RA bill's value is the sum
-- of its lines is the service's job (apps/payables/work_orders.py).
CREATE FUNCTION vendor_bills_work_order() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  wo record;
BEGIN
  IF NEW.work_order_id IS NULL THEN
    IF NEW.retention_amount <> 0 OR NEW.ra_number IS NOT NULL THEN
      RAISE EXCEPTION 'retention and an RA number belong to RA bills against a work order'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND (NEW.work_order_id IS DISTINCT FROM OLD.work_order_id
                           OR NEW.ra_number IS DISTINCT FROM OLD.ra_number) THEN
    RAISE EXCEPTION 'an RA bill keeps its work order and number' USING ERRCODE = 'check_violation';
  END IF;
  SELECT vendor_party_id, project_id, status INTO wo FROM work_orders WHERE id = NEW.work_order_id;
  IF wo.vendor_party_id IS DISTINCT FROM NEW.vendor_party_id
     OR wo.project_id IS DISTINCT FROM NEW.project_id THEN
    RAISE EXCEPTION 'an RA bill is from the work order''s subcontractor, for its project'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'INSERT' AND wo.status <> 'OPEN' THEN
    RAISE EXCEPTION 'the work order is closed' USING ERRCODE = 'check_violation';
  END IF;
  -- Voiding an RA bill must leave enough retention held for what is released.
  IF TG_OP = 'UPDATE' AND OLD.status = 'RECORDED' AND NEW.status = 'VOIDED' THEN
    PERFORM 1 FROM work_orders WHERE id = NEW.work_order_id FOR UPDATE;
    IF (SELECT coalesce(sum(amount), 0) FROM vendor_retention_releases
         WHERE work_order_id = NEW.work_order_id AND status = 'RELEASED')
       > (SELECT coalesce(sum(retention_amount), 0) FROM vendor_bills
           WHERE work_order_id = NEW.work_order_id AND status = 'RECORDED' AND id <> NEW.id) THEN
      RAISE EXCEPTION 'retention from this bill is released; cancel the release first'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER vendor_bills_work_order
  BEFORE INSERT OR UPDATE ON vendor_bills
  FOR EACH ROW EXECUTE FUNCTION vendor_bills_work_order();

CREATE FUNCTION vendor_bill_lines_check() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  bill    record;
  item    record;
  billed  numeric;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'RA bill lines are not changed; delete and re-create' USING ERRCODE = 'check_violation';
  END IF;

  SELECT status, work_order_id, amount_paid INTO bill FROM vendor_bills
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.vendor_bill_id ELSE NEW.vendor_bill_id END;
  IF bill.status IS DISTINCT FROM 'RECORDED' OR bill.amount_paid > 0 THEN
    RAISE EXCEPTION 'the lines of a paid or voided RA bill do not change' USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;

  SELECT work_order_id, qty INTO item FROM work_order_items WHERE id = NEW.work_order_item_id FOR UPDATE;
  IF item.work_order_id IS DISTINCT FROM bill.work_order_id THEN
    RAISE EXCEPTION 'an RA bill line is an item of the bill''s work order' USING ERRCODE = 'check_violation';
  END IF;
  SELECT coalesce(sum(l.qty), 0) INTO billed
    FROM vendor_bill_lines l JOIN vendor_bills b ON b.id = l.vendor_bill_id
   WHERE l.work_order_item_id = NEW.work_order_item_id AND b.status = 'RECORDED';
  IF billed + NEW.qty > item.qty THEN
    RAISE EXCEPTION 'billed quantity would exceed the work order quantity' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER vendor_bill_lines_check
  BEFORE INSERT OR UPDATE OR DELETE ON vendor_bill_lines
  FOR EACH ROW EXECUTE FUNCTION vendor_bill_lines_check();

CREATE FUNCTION work_order_items_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  billed numeric;
BEGIN
  IF NEW.work_order_id IS DISTINCT FROM OLD.work_order_id THEN
    RAISE EXCEPTION 'an item stays on its work order' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.qty < OLD.qty THEN
    SELECT coalesce(sum(l.qty), 0) INTO billed
      FROM vendor_bill_lines l JOIN vendor_bills b ON b.id = l.vendor_bill_id
     WHERE l.work_order_item_id = NEW.id AND b.status = 'RECORDED';
    IF NEW.qty < billed THEN
      RAISE EXCEPTION 'the quantity cannot be less than what is already billed'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER work_order_items_guard
  BEFORE UPDATE ON work_order_items
  FOR EACH ROW EXECUTE FUNCTION work_order_items_guard();

-- Retention released to a subcontractor is never more than is still held on
-- the work order's recorded RA bills; the work order row is locked so two
-- releases at once cannot both pass. A release keeps its work order and
-- amount (cancel it and release again).
CREATE FUNCTION vendor_retention_releases_check() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  wo        record;
  held      numeric;
  released  numeric;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.work_order_id IS DISTINCT FROM OLD.work_order_id
       OR NEW.vendor_party_id IS DISTINCT FROM OLD.vendor_party_id
       OR NEW.amount IS DISTINCT FROM OLD.amount THEN
      RAISE EXCEPTION 'a retention release keeps its work order and amount'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  SELECT vendor_party_id INTO wo FROM work_orders WHERE id = NEW.work_order_id FOR UPDATE;
  IF wo.vendor_party_id IS DISTINCT FROM NEW.vendor_party_id THEN
    RAISE EXCEPTION 'retention is released to the work order''s subcontractor'
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT coalesce(sum(retention_amount), 0) INTO held FROM vendor_bills
   WHERE work_order_id = NEW.work_order_id AND status = 'RECORDED';
  SELECT coalesce(sum(amount), 0) INTO released FROM vendor_retention_releases
   WHERE work_order_id = NEW.work_order_id AND status = 'RELEASED';
  IF released + NEW.amount > held THEN
    RAISE EXCEPTION 'more than the retention still held on the work order'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER vendor_retention_releases_check
  BEFORE INSERT OR UPDATE ON vendor_retention_releases
  FOR EACH ROW EXECUTE FUNCTION vendor_retention_releases_check();

-- Site diary photos are photos: an image attachment that passed the virus check.
CREATE FUNCTION site_diary_photos_check() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  file record;
BEGIN
  SELECT content_type, status INTO file FROM attachments WHERE id = NEW.attachment_id;
  IF file.status IS DISTINCT FROM 'AVAILABLE' OR file.content_type NOT LIKE 'image/%' THEN
    RAISE EXCEPTION 'a diary photo is an image that passed the virus check'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER site_diary_photos_check
  BEFORE INSERT OR UPDATE OF attachment_id ON site_diary_photos
  FOR EACH ROW EXECUTE FUNCTION site_diary_photos_check();

-- A bill's photos are from its own project's diary.
CREATE FUNCTION document_photos_check() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM documents d
      JOIN site_diary_photos p ON p.id = NEW.diary_photo_id
      JOIN site_diary_entries e ON e.id = p.entry_id
     WHERE d.id = NEW.document_id AND d.project_id = e.project_id
  ) THEN
    RAISE EXCEPTION 'a bill''s photos are from its project''s site diary'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER document_photos_check
  BEFORE INSERT OR UPDATE ON document_photos
  FOR EACH ROW EXECUTE FUNCTION document_photos_check();

-- 7d. Audit trail. SECURITY DEFINER so the app role needs no INSERT right on
--     audit_log (it cannot forge or bulk-write audit rows directly).
CREATE FUNCTION audit_row_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  old_j jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
  new_j jsonb := CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END;
  r     jsonb := coalesce(new_j, old_j);
BEGIN
  IF TG_OP = 'UPDATE' AND old_j = new_j THEN
    RETURN NULL;
  END IF;
  INSERT INTO audit_log (tenant_id, actor_user_id, request_id, action, table_name, row_id, old_data, new_data)
  VALUES (
    CASE WHEN TG_TABLE_NAME = 'tenants' THEN (r ->> 'id')::uuid ELSE (r ->> 'tenant_id')::uuid END,
    app_current_user_id(),
    NULLIF(current_setting('app.request_id', true), ''),
    TG_OP, TG_TABLE_NAME, (r ->> 'id')::uuid, old_j, new_j);
  RETURN NULL;
END $$;

CREATE FUNCTION audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_log_no_update
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
CREATE TRIGGER audit_log_no_truncate
  BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'tenants', 'memberships', 'gst_registrations', 'parties', 'projects', 'boq_items',
    'catalog_items', 'attachments', 'document_series', 'documents', 'document_lines',
    'payments', 'allocations', 'expenses', 'retention_releases', 'tds_certificates', 'exports',
    'email_invitations', 'payment_reminders', 'document_templates', 'catalog_item_variants',
    'document_line_measurements', 'print_settings', 'document_emails', 'tally_settings',
    'vendor_bills', 'vendor_payments', 'vendor_allocations', 'bank_lines', 'work_orders',
    'work_order_items', 'vendor_bill_lines', 'vendor_retention_releases', 'gstr2b_returns',
    'site_diary_entries', 'site_diary_photos', 'document_photos']
  LOOP
    EXECUTE format(
      'CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION audit_row_change()', t);
  END LOOP;
END $$;

-- =============================================================================
-- 8. Row-Level Security
-- =============================================================================

-- Standard policy: a row is visible/writable only inside its own tenant.
-- FORCE makes it apply to the table owner too (defence in depth).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'gst_registrations', 'parties', 'projects', 'boq_items', 'catalog_items', 'attachments',
    'document_series', 'documents', 'document_lines', 'payments', 'allocations', 'expenses',
    'retention_releases', 'tds_certificates', 'idempotency_keys', 'exports', 'email_invitations',
    'payment_reminders', 'document_templates', 'catalog_item_variants', 'document_line_measurements',
    'print_settings', 'document_emails', 'tally_settings', 'vendor_bills', 'vendor_payments',
    'vendor_allocations', 'bank_lines', 'work_orders', 'work_order_items', 'vendor_bill_lines',
    'vendor_retention_releases', 'gstr2b_returns', 'gstr2b_lines', 'notifications',
    'site_diary_entries', 'site_diary_photos', 'document_photos']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = app_current_tenant()) '
      'WITH CHECK (tenant_id = app_current_tenant())', t);
  END LOOP;
END $$;

-- tenants: the current tenant, plus (read-only) every tenant the signed-in
-- user is an active member of — needed for the tenant switcher at login —
-- or has a pending invitation from, so the invitee sees who invited them.
-- Creating a tenant: the app generates the id, sets app.tenant_id to it, then
-- inserts the tenant and the OWNER membership in the same transaction.
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON tenants
  USING (id = app_current_tenant()) WITH CHECK (id = app_current_tenant());
CREATE POLICY tenant_member_read ON tenants FOR SELECT
  USING (EXISTS (SELECT 1 FROM memberships m
                  WHERE m.tenant_id = tenants.id
                    AND m.user_id = app_current_user_id()
                    AND m.status IN ('ACTIVE', 'INVITED')));

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY membership_tenant ON memberships
  USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
CREATE POLICY membership_own_read ON memberships FOR SELECT
  USING (user_id = app_current_user_id());

-- Accepting / declining an invitation. The invitee is signed in to some other
-- tenant (or none), so the tenant policy hides the invitation from UPDATE. This
-- function is the one narrow way through: it changes only the status of the
-- current user's own INVITED membership, switching app.tenant_id to that
-- tenant for the single UPDATE and restoring it afterwards. A broader UPDATE
-- policy could not stop the invitee from changing their role at the same time.
CREATE FUNCTION respond_to_invitation(p_membership_id uuid, p_accept boolean) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
  inv_tenant  uuid;
  prev_tenant text := current_setting('app.tenant_id', true);
BEGIN
  SELECT tenant_id INTO inv_tenant FROM memberships          -- visible via membership_own_read
   WHERE id = p_membership_id AND user_id = app_current_user_id() AND status = 'INVITED';
  IF inv_tenant IS NULL THEN
    RAISE EXCEPTION 'no pending invitation % for the current user', p_membership_id
      USING ERRCODE = 'no_data_found';
  END IF;
  PERFORM set_config('app.tenant_id', inv_tenant::text, true);
  UPDATE memberships
     SET status = CASE WHEN p_accept THEN 'ACTIVE' ELSE 'REVOKED' END, updated_at = now()
   WHERE id = p_membership_id;
  PERFORM set_config('app.tenant_id', coalesce(prev_tenant, ''), true);
  RETURN inv_tenant;
END $$;

-- audit_log: readable per tenant; rows are only ever inserted by the
-- SECURITY DEFINER trigger (owner), so RLS is enabled but not forced.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_tenant_read ON audit_log FOR SELECT
  USING (tenant_id = app_current_tenant());

-- Someone invited by email signed up the normal way: their pending email
-- invitations, in any tenant, become INVITED memberships (shown in their
-- invitations banner). Runs as the owner, who alone sees invitations across
-- tenants (policy below), and only for the user's own address.
CREATE POLICY claim_by_email ON email_invitations
  USING (current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class
                          WHERE oid = 'email_invitations'::regclass));

CREATE FUNCTION claim_email_invitations(p_user_id uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  r       record;
  n       integer := 0;
  address citext;
  prev    text := current_setting('app.tenant_id', true);
BEGIN
  SELECT email INTO address FROM users WHERE id = p_user_id;
  FOR r IN SELECT id, tenant_id, role, party_id, invited_by FROM email_invitations
            WHERE email = address AND status = 'PENDING' AND expires_at > now()
            FOR UPDATE
  LOOP
    PERFORM set_config('app.tenant_id', r.tenant_id::text, true);
    INSERT INTO memberships (tenant_id, user_id, role, party_id, status, invited_by)
      VALUES (r.tenant_id, p_user_id, r.role, r.party_id, 'INVITED', r.invited_by)
      ON CONFLICT (tenant_id, user_id) DO NOTHING;
    UPDATE email_invitations SET status = 'ACCEPTED', accepted_by = p_user_id, updated_at = now()
     WHERE id = r.id;
    n := n + 1;
  END LOOP;
  PERFORM set_config('app.tenant_id', coalesce(prev, ''), true);
  RETURN n;
END $$;

REVOKE ALL ON FUNCTION claim_email_invitations(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_email_invitations(uuid) TO billing_app;

-- Client portal (W.5). A CLIENT session also sets app.party_id; these
-- RESTRICTIVE policies are ANDed with the tenant policies above and narrow
-- every table to that client's own, issued rows. Staff sessions (party
-- unset) pass them unchanged. The EXISTS forms rely on the RLS of the table
-- they read (documents, projects, retention_releases), so "the client's
-- issued documents" is written once. A new tenant table must get one too
-- (tests/db/test_roles_and_rls.py checks).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'gst_registrations', 'catalog_items', 'catalog_item_variants', 'document_series', 'expenses',
    'tds_certificates', 'email_invitations', 'payment_reminders', 'document_templates', 'audit_log',
    'print_settings', 'document_emails', 'tally_settings', 'vendor_bills', 'vendor_payments',
    'vendor_allocations', 'bank_lines', 'work_orders', 'work_order_items', 'vendor_bill_lines',
    'vendor_retention_releases', 'gstr2b_returns', 'gstr2b_lines', 'notifications']
  LOOP
    EXECUTE format(
      'CREATE POLICY client_scope ON %I AS RESTRICTIVE USING (NOT app_portal_session())', t);
  END LOOP;
END $$;

-- notifications: each person reads and marks only their own (anyone in the
-- business may be sent one).
CREATE POLICY own_rows_read ON notifications AS RESTRICTIVE FOR SELECT
  USING (user_id = app_current_user_id());
CREATE POLICY own_rows_update ON notifications AS RESTRICTIVE FOR UPDATE
  USING (user_id = app_current_user_id());
CREATE POLICY client_scope ON parties AS RESTRICTIVE
  USING (NOT app_portal_session() OR id = app_current_party());
CREATE POLICY client_scope ON projects AS RESTRICTIVE
  USING (NOT app_portal_session() OR client_party_id = app_current_party());
CREATE POLICY client_scope ON boq_items AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM projects p
                     WHERE p.tenant_id = boq_items.tenant_id AND p.id = boq_items.project_id));
CREATE POLICY client_scope ON documents AS RESTRICTIVE
  USING (NOT app_portal_session() OR (party_id = app_current_party() AND status <> 'DRAFT'));
CREATE POLICY client_scope ON document_lines AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = document_lines.tenant_id AND d.id = document_lines.document_id));
CREATE POLICY client_scope ON document_line_measurements AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = document_line_measurements.tenant_id
                       AND d.id = document_line_measurements.document_id));
CREATE POLICY client_scope ON payments AS RESTRICTIVE
  USING (NOT app_portal_session() OR (party_id = app_current_party() AND status = 'RECORDED'));
CREATE POLICY client_scope ON retention_releases AS RESTRICTIVE
  USING (NOT app_portal_session() OR (party_id = app_current_party() AND status = 'RELEASED'));
CREATE POLICY client_scope ON allocations AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = allocations.tenant_id AND d.id = allocations.document_id)
         OR EXISTS (SELECT 1 FROM retention_releases r
                     WHERE r.tenant_id = allocations.tenant_id AND r.id = allocations.retention_release_id));
CREATE POLICY client_scope ON attachments AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = attachments.tenant_id AND d.pdf_attachment_id = attachments.id)
         OR EXISTS (SELECT 1 FROM site_diary_photos p
                     WHERE p.tenant_id = attachments.tenant_id AND p.attachment_id = attachments.id));
-- Proof of work: a client sees the photos chosen for their own bills, the
-- diary day they are from and the image files, nothing else of the diary.
CREATE POLICY client_scope ON document_photos AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = document_photos.tenant_id AND d.id = document_photos.document_id));
CREATE POLICY client_scope ON site_diary_photos AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM document_photos dp
                     WHERE dp.tenant_id = site_diary_photos.tenant_id
                       AND dp.diary_photo_id = site_diary_photos.id));
CREATE POLICY client_scope ON site_diary_entries AS RESTRICTIVE
  USING (NOT app_portal_session()
         OR EXISTS (SELECT 1 FROM site_diary_photos p
                     WHERE p.tenant_id = site_diary_entries.tenant_id AND p.entry_id = site_diary_entries.id));
CREATE POLICY client_scope ON idempotency_keys AS RESTRICTIVE
  USING (NOT app_portal_session() OR user_id = app_current_user_id());
CREATE POLICY client_scope ON exports AS RESTRICTIVE
  USING (NOT app_portal_session() OR requested_by = app_current_user_id());
CREATE POLICY client_scope ON memberships AS RESTRICTIVE
  USING (NOT app_portal_session() OR user_id = app_current_user_id());
-- The client may read the business's own row (its name), never change it.
CREATE POLICY client_scope ON tenants AS RESTRICTIVE FOR UPDATE
  USING (NOT app_portal_session());

-- users and auth_sessions have no tenant; the app only ever reads them by
-- primary key, email or token hash, and never lists them across tenants.

-- Housekeeping. Workers have no tenant context, so purges run through these
-- SECURITY DEFINER functions as the table owner. RLS stays forced: the
-- policies below let the owner (and nobody else) see exactly the rows to
-- purge, so even these functions cannot read anything else.
CREATE POLICY housekeeping_purge ON idempotency_keys
  USING (expires_at < now()
         AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class
                              WHERE oid = 'idempotency_keys'::regclass));
CREATE POLICY housekeeping_purge ON attachments
  USING (status = 'PENDING' AND created_at < now() - interval '1 day'
         AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class
                              WHERE oid = 'attachments'::regclass));

CREATE FUNCTION purge_expired_idempotency_keys() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE n integer;
BEGIN
  DELETE FROM idempotency_keys WHERE expires_at < now();
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- Uploads never completed within a day: deletes the rows and returns their
-- storage keys, so the caller deletes the objects in the same transaction.
CREATE FUNCTION purge_stale_uploads(p_limit integer) RETURNS SETOF text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id, storage_key FROM attachments
            WHERE status = 'PENDING' AND created_at < now() - interval '1 day'
            ORDER BY created_at LIMIT p_limit
            FOR UPDATE SKIP LOCKED
  LOOP
    BEGIN
      DELETE FROM attachments WHERE id = r.id;
      RETURN NEXT r.storage_key;
    EXCEPTION WHEN foreign_key_violation THEN
      NULL;  -- linked to something after all: keep it
    END;
  END LOOP;
END $$;

REVOKE ALL ON FUNCTION purge_expired_idempotency_keys(), purge_stale_uploads(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION purge_expired_idempotency_keys(), purge_stale_uploads(integer) TO billing_app;

CREATE POLICY housekeeping_purge ON exports
  USING (created_at < now() - interval '7 days'
         AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class
                              WHERE oid = 'exports'::regclass));

-- Exports older than 7 days: deletes the rows and returns the storage keys of
-- their files, so the caller deletes those in the same transaction.
CREATE FUNCTION purge_old_exports(p_limit integer) RETURNS SETOF text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record;
BEGIN
  FOR r IN SELECT id, storage_key FROM exports
            WHERE created_at < now() - interval '7 days'
            ORDER BY created_at LIMIT p_limit
            FOR UPDATE SKIP LOCKED
  LOOP
    DELETE FROM exports WHERE id = r.id;
    IF r.storage_key IS NOT NULL THEN
      RETURN NEXT r.storage_key;
    END IF;
  END LOOP;
END $$;

REVOKE ALL ON FUNCTION purge_old_exports(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION purge_old_exports(integer) TO billing_app;

-- The daily payment-reminder job (W.2) visits each active tenant in turn and
-- works inside that tenant's context; across tenants it may see only their
-- ids and time zones (each tenant's "today").
CREATE POLICY housekeeping_reminders ON tenants FOR SELECT
  USING (status = 'ACTIVE'
         AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class
                              WHERE oid = 'tenants'::regclass));

CREATE FUNCTION active_tenants() RETURNS TABLE (tenant_id uuid, time_zone text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT id, timezone FROM tenants WHERE status = 'ACTIVE' ORDER BY id
$$;
REVOKE ALL ON FUNCTION active_tenants() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION active_tenants() TO billing_app;

-- =============================================================================
-- 9. Reporting views
--    security_invoker = true is REQUIRED: a normal view runs with its owner's
--    rights and would silently bypass RLS, leaking every tenant's data.
-- =============================================================================

-- Owner dashboard: billing by month, split into books, with a combined total
-- available by simply not filtering on `book`.
CREATE VIEW v_billing_summary WITH (security_invoker = true) AS
SELECT
  d.tenant_id,
  date_trunc('month', d.doc_date)::date                         AS month,
  CASE WHEN d.is_gst_document THEN 'GST' ELSE 'NON_GST' END      AS book,
  d.project_id,
  count(*)                                                       AS document_count,
  sum(CASE WHEN d.doc_type = 'CREDIT_NOTE' THEN -d.subtotal    ELSE d.subtotal    END) AS taxable_value,
  -- tax charged by us: reverse-charge tax is paid by the recipient
  sum(CASE WHEN d.reverse_charge THEN 0
           WHEN d.doc_type = 'CREDIT_NOTE' THEN -(d.cgst_amount + d.sgst_amount + d.igst_amount + d.cess_amount)
           ELSE  (d.cgst_amount + d.sgst_amount + d.igst_amount + d.cess_amount) END) AS tax,
  sum(CASE WHEN d.doc_type = 'CREDIT_NOTE' THEN -d.grand_total ELSE d.grand_total END) AS billed
FROM documents d
WHERE d.is_revenue AND d.status = 'ISSUED'
GROUP BY 1, 2, 3, 4;

-- Money owed now: unsettled invoices, bills of supply, debit notes and
-- retention releases (document_id or retention_release_id is set).
CREATE VIEW v_receivables WITH (security_invoker = true) AS
SELECT
  d.tenant_id, d.id AS document_id, NULL::uuid AS retention_release_id,
  d.doc_type, d.doc_number, d.doc_date, d.due_date,
  d.party_id, d.project_id, d.is_gst_document,
  d.net_receivable, d.amount_settled,
  d.net_receivable - d.amount_settled AS outstanding,
  CASE
    WHEN current_date - coalesce(d.due_date, d.doc_date) <= 0  THEN 'NOT_DUE'
    WHEN current_date - coalesce(d.due_date, d.doc_date) <= 30 THEN '1_30'
    WHEN current_date - coalesce(d.due_date, d.doc_date) <= 60 THEN '31_60'
    WHEN current_date - coalesce(d.due_date, d.doc_date) <= 90 THEN '61_90'
    ELSE '90_PLUS'
  END AS ageing_bucket
FROM documents d
WHERE d.status = 'ISSUED'
  AND d.doc_type IN ('TAX_INVOICE', 'BILL_OF_SUPPLY', 'DEBIT_NOTE')
  AND d.amount_settled < d.net_receivable
UNION ALL
SELECT
  r.tenant_id, NULL::uuid, r.id,
  'RETENTION_RELEASE', r.reference, r.release_date, r.due_date,
  r.party_id, r.project_id, r.book = 'GST',
  r.amount, r.amount_settled,
  r.amount - r.amount_settled,
  CASE
    WHEN current_date - coalesce(r.due_date, r.release_date) <= 0  THEN 'NOT_DUE'
    WHEN current_date - coalesce(r.due_date, r.release_date) <= 30 THEN '1_30'
    WHEN current_date - coalesce(r.due_date, r.release_date) <= 60 THEN '31_60'
    WHEN current_date - coalesce(r.due_date, r.release_date) <= 90 THEN '61_90'
    ELSE '90_PLUS'
  END
FROM retention_releases r
WHERE r.status = 'RELEASED' AND r.amount_settled < r.amount;

-- Per project. Retention held = deducted on issued bills - released; the
-- outstanding includes unsettled retention releases.
CREATE VIEW v_project_billing WITH (security_invoker = true) AS
SELECT
  p.tenant_id, p.id AS project_id, p.code, p.name, p.contract_value,
  coalesce(d.billed_taxable, 0)                                  AS billed_taxable,
  coalesce(d.retention_deducted, 0) - coalesce(r.released, 0)    AS retention_held,
  coalesce(r.released, 0)                                        AS retention_released,
  coalesce(d.tds_deducted, 0)                                    AS tds_deducted,
  coalesce(d.advance_recovered, 0)                               AS advance_recovered,
  coalesce(d.outstanding, 0) + coalesce(r.outstanding, 0)        AS outstanding
FROM projects p
LEFT JOIN (
  SELECT tenant_id, project_id,
         sum(CASE WHEN doc_type = 'CREDIT_NOTE' THEN -subtotal ELSE subtotal END) AS billed_taxable,
         sum(retention_amount)                                    AS retention_deducted,
         sum(income_tax_tds_amount + gst_tds_amount)              AS tds_deducted,
         sum(advance_recovery_amount)                             AS advance_recovered,
         sum(net_receivable - amount_settled) FILTER (WHERE doc_type <> 'CREDIT_NOTE') AS outstanding
    FROM documents
   WHERE status = 'ISSUED' AND is_revenue AND project_id IS NOT NULL
   GROUP BY tenant_id, project_id
) d ON d.tenant_id = p.tenant_id AND d.project_id = p.id
LEFT JOIN (
  SELECT tenant_id, project_id, sum(amount) AS released, sum(amount - amount_settled) AS outstanding
    FROM retention_releases
   WHERE status = 'RELEASED'
   GROUP BY tenant_id, project_id
) r ON r.tenant_id = p.tenant_id AND r.project_id = p.id;

-- =============================================================================
-- 10. Privileges for the application role
-- =============================================================================

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO billing_app;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO billing_app;
-- Hard deletes only where they are part of the design (drafts, unwinding
-- allocations, editable masters, housekeeping). Everything else is
-- cancelled / voided / archived instead.
GRANT DELETE ON documents, document_lines, allocations, boq_items, catalog_items, tds_certificates,
                idempotency_keys, auth_sessions, document_templates, catalog_item_variants,
                document_line_measurements, vendor_allocations, work_order_items,
                vendor_bill_lines, gstr2b_returns, gstr2b_lines, site_diary_photos,
                document_photos TO billing_app;
-- Audit rows are written only by the trigger.
REVOKE INSERT, UPDATE, DELETE ON audit_log FROM billing_app;
REVOKE INSERT, UPDATE ON v_billing_summary, v_receivables, v_project_billing FROM billing_app;
-- Settlement totals are owned by the allocations trigger.
REVOKE UPDATE ON documents FROM billing_app;
GRANT UPDATE (status, doc_type, gst_registration_id, series_id, doc_number, doc_date, due_date, valid_until,
              party_id, project_id, source_document_id, original_document_id, is_ra_bill, ra_sequence,
              supplier_snapshot, party_snapshot, place_of_supply, supply_type, reverse_charge,
              supply_category, lut,
              subtotal, cgst_amount, sgst_amount, igst_amount, cess_amount, round_off, round_to_rupee, grand_total,
              retention_amount, income_tax_tds_amount, gst_tds_amount, advance_recovery_amount, net_receivable,
              notes, terms, pdf_attachment_id, issued_at, issued_by, cancelled_at, cancelled_by, cancel_reason,
              approval_requested_at, approval_requested_by, approved_version, approved_at, approved_by,
              version, updated_at)
  ON documents TO billing_app;
-- Retention releases: settlement owned by the allocations trigger; otherwise
-- only cancelled, never edited or deleted.
REVOKE UPDATE ON retention_releases FROM billing_app;
GRANT UPDATE (status, cancelled_at, cancelled_by, cancel_reason, version, updated_at)
  ON retention_releases TO billing_app;
-- Vendor bills: what was paid is owned by the vendor allocations trigger (Part B).
REVOKE UPDATE ON vendor_bills FROM billing_app;
GRANT UPDATE (vendor_party_id, project_id, bill_number, bill_date, due_date, category, description,
              taxable_value, gst_amount, total_amount, itc_eligible, tds_section, tds_rate, tds_amount,
              net_payable, retention_amount, attachment_id, notes, status, voided_at, voided_by,
              void_reason, version, updated_at)
  ON vendor_bills TO billing_app;
-- RA bill lines are written once (deleted and re-written while the bill is unpaid).
REVOKE UPDATE ON vendor_bill_lines FROM billing_app;
-- Retention released to subcontractors: paid by the trigger, otherwise only cancelled.
REVOKE UPDATE ON vendor_retention_releases FROM billing_app;
-- GSTR-2B as uploaded: never edited, only replaced by the next upload of the month.
REVOKE UPDATE ON gstr2b_returns, gstr2b_lines FROM billing_app;
-- Notifications: only marked read.
REVOKE UPDATE ON notifications FROM billing_app;
GRANT UPDATE (read_at) ON notifications TO billing_app;
-- A bill's photos are chosen or taken off, never changed.
REVOKE UPDATE ON document_photos FROM billing_app;
GRANT UPDATE (status, cancelled_at, cancelled_by, cancel_reason, version, updated_at)
  ON vendor_retention_releases TO billing_app;
-- Payment reminders are a log: written once, never changed.
REVOKE UPDATE ON payment_reminders FROM billing_app;
-- Emailed bills: a log, written once (B.15).
REVOKE UPDATE ON document_emails FROM billing_app;

COMMIT;
