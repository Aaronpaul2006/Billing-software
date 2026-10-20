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
  password_hash      text NOT NULL,                       -- argon2id encoded string
  full_name          text NOT NULL CHECK (char_length(full_name) BETWEEN 1 AND 200),
  phone              text CHECK (phone ~ '^\+?[0-9]{10,15}$'),
  mfa_enabled        boolean NOT NULL DEFAULT false,
  mfa_secret_enc     bytea,                               -- TOTP secret, envelope-encrypted by the app
  mfa_recovery_codes text[] NOT NULL DEFAULT '{}',        -- SHA-256 (hex) of unused one-time recovery codes
  mfa_last_used_step bigint,                              -- last accepted TOTP time step (no code replay)
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
  version     integer NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- A user can belong to several tenants (e.g. an accountant serving many firms).
CREATE TABLE memberships (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants (id),
  user_id     uuid NOT NULL REFERENCES users (id),
  role        text NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'ACCOUNTANT', 'SITE_ENGINEER', 'VIEWER')),
  status      text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('INVITED', 'ACTIVE', 'REVOKED')),
  invited_by  uuid REFERENCES users (id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, user_id)
);
CREATE INDEX memberships_user_idx ON memberships (user_id);

-- Refresh-token sessions. Only a SHA-256 of the opaque token is stored.
-- Rotation: each refresh issues a new row in the same family; presenting an
-- already-rotated token revokes the whole family (token theft detection).
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
  revoked_at          timestamptz
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
  version            integer NOT NULL DEFAULT 1,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  CHECK ((registration_type = 'UNREGISTERED') = (gstin IS NULL)),
  CHECK (gstin IS NULL OR substr(gstin, 1, 2) = state_code)
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
  reverse_charge           boolean NOT NULL DEFAULT false,
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
  CHECK (grand_total = subtotal + cgst_amount + sgst_amount + igst_amount + cess_amount + round_off),
  CHECK (net_receivable = grand_total - retention_amount - income_tax_tds_amount - gst_tds_amount - advance_recovery_amount),
  CHECK (amount_settled >= 0 AND amount_settled <= net_receivable),
  CHECK (due_date IS NULL OR due_date >= doc_date)
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
  boq_item_id          uuid,
  description          text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 2000),
  sac_hsn              text CHECK (sac_hsn ~ '^[0-9]{4,8}$'),
  unit                 text,
  quantity             numeric(14,3) NOT NULL CHECK (quantity > 0),       -- RA bill: quantity in THIS bill
  prev_cumulative_qty  numeric(14,3) CHECK (prev_cumulative_qty >= 0),    -- RA bill: billed up to the previous bill (snapshot)
  rate                 numeric(14,2) NOT NULL CHECK (rate >= 0),
  discount_amount      numeric(14,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
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
  FOREIGN KEY (tenant_id, boq_item_id)     REFERENCES boq_items (tenant_id, id),
  CHECK (taxable_value = round(quantity * rate, 2) - discount_amount),
  CHECK (cgst_amount = sgst_amount),
  CHECK (line_total = taxable_value + cgst_amount + sgst_amount + igst_amount + cess_amount)
);
CREATE INDEX document_lines_boq_idx ON document_lines (tenant_id, boq_item_id) WHERE boq_item_id IS NOT NULL;

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
      SELECT registration_type, state_code INTO reg
        FROM gst_registrations WHERE id = NEW.gst_registration_id;
      IF reg.registration_type <> 'REGULAR' AND NEW.doc_type IN ('TAX_INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE') THEN
        RAISE EXCEPTION '% registration cannot issue %; use BILL_OF_SUPPLY', reg.registration_type, NEW.doc_type
          USING ERRCODE = 'check_violation';
      END IF;
      IF reg.registration_type = 'REGULAR'
         AND NEW.supply_type <> (CASE WHEN NEW.place_of_supply = reg.state_code THEN 'INTRA_STATE' ELSE 'INTER_STATE' END) THEN
        RAISE EXCEPTION 'supply_type does not match place of supply %', NEW.place_of_supply
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
    'payments', 'allocations', 'expenses', 'retention_releases', 'tds_certificates']
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
    'retention_releases', 'tds_certificates', 'idempotency_keys']
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

-- users and auth_sessions have no tenant; the app only ever reads them by
-- primary key, email or token hash, and never lists them across tenants.

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
  sum(CASE WHEN d.doc_type = 'CREDIT_NOTE' THEN -(d.cgst_amount + d.sgst_amount + d.igst_amount + d.cess_amount)
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
                idempotency_keys, auth_sessions TO billing_app;
-- Audit rows are written only by the trigger.
REVOKE INSERT, UPDATE, DELETE ON audit_log FROM billing_app;
REVOKE INSERT, UPDATE ON v_billing_summary, v_receivables, v_project_billing FROM billing_app;
-- Settlement totals are owned by the allocations trigger.
REVOKE UPDATE ON documents FROM billing_app;
GRANT UPDATE (status, doc_type, gst_registration_id, series_id, doc_number, doc_date, due_date, valid_until,
              party_id, project_id, source_document_id, original_document_id, is_ra_bill, ra_sequence,
              supplier_snapshot, party_snapshot, place_of_supply, supply_type, reverse_charge,
              subtotal, cgst_amount, sgst_amount, igst_amount, cess_amount, round_off, round_to_rupee, grand_total,
              retention_amount, income_tax_tds_amount, gst_tds_amount, advance_recovery_amount, net_receivable,
              notes, terms, pdf_attachment_id, issued_at, issued_by, cancelled_at, cancelled_by, cancel_reason,
              version, updated_at)
  ON documents TO billing_app;
-- Retention releases: settlement owned by the allocations trigger; otherwise
-- only cancelled, never edited or deleted.
REVOKE UPDATE ON retention_releases FROM billing_app;
GRANT UPDATE (status, cancelled_at, cancelled_by, cancel_reason, version, updated_at)
  ON retention_releases TO billing_app;

COMMIT;
