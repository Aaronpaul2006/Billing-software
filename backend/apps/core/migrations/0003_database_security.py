"""Database-enforced rules, copied from db/schema.sql sections 7-10.

Composite foreign keys, integrity triggers, the audit trail, Row-Level
Security, reporting views and privileges. The SQL is frozen here as it was
when this migration was written: a later change to db/schema.sql needs a new
migration (tests/db/test_schema_sync.py fails until the two match again).

The billing_app role must exist (scripts/bootstrap_db.py); otherwise this
migration fails loudly instead of silently granting nothing.
"""

from django.db import migrations

FOREIGN_KEYS = r"""
-- Foreign keys exactly as in db/schema.sql. Django's own FK constraints are
-- disabled (db_constraint=False): between tenant tables the key is composite
-- (tenant_id, x_id) -> parent (tenant_id, id) because PostgreSQL skips RLS
-- during FK checks, so a single-column key would allow cross-tenant links.
ALTER TABLE memberships
  ADD FOREIGN KEY (tenant_id)  REFERENCES tenants (id),
  ADD FOREIGN KEY (user_id)    REFERENCES users (id),
  ADD FOREIGN KEY (invited_by) REFERENCES users (id);
ALTER TABLE auth_sessions
  ADD FOREIGN KEY (user_id)   REFERENCES users (id),
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE gst_registrations
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE parties
  ADD FOREIGN KEY (tenant_id)  REFERENCES tenants (id),
  ADD FOREIGN KEY (created_by) REFERENCES users (id);
ALTER TABLE projects
  ADD FOREIGN KEY (tenant_id)  REFERENCES tenants (id),
  ADD FOREIGN KEY (created_by) REFERENCES users (id),
  ADD FOREIGN KEY (tenant_id, client_party_id)     REFERENCES parties (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, gst_registration_id) REFERENCES gst_registrations (tenant_id, id);
ALTER TABLE boq_items
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  ADD FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id);
ALTER TABLE catalog_items
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE attachments
  ADD FOREIGN KEY (tenant_id)   REFERENCES tenants (id),
  ADD FOREIGN KEY (uploaded_by) REFERENCES users (id);
ALTER TABLE document_series
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  ADD FOREIGN KEY (tenant_id, gst_registration_id) REFERENCES gst_registrations (tenant_id, id);
ALTER TABLE documents
  ADD FOREIGN KEY (tenant_id)    REFERENCES tenants (id),
  ADD FOREIGN KEY (issued_by)    REFERENCES users (id),
  ADD FOREIGN KEY (cancelled_by) REFERENCES users (id),
  ADD FOREIGN KEY (created_by)   REFERENCES users (id),
  ADD FOREIGN KEY (tenant_id, gst_registration_id)  REFERENCES gst_registrations (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, series_id)            REFERENCES document_series (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, party_id)             REFERENCES parties (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, project_id)           REFERENCES projects (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, source_document_id)   REFERENCES documents (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, original_document_id) REFERENCES documents (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, pdf_attachment_id)    REFERENCES attachments (tenant_id, id);
ALTER TABLE document_lines
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  ADD FOREIGN KEY (tenant_id, document_id)     REFERENCES documents (tenant_id, id) ON DELETE CASCADE,
  ADD FOREIGN KEY (tenant_id, catalog_item_id) REFERENCES catalog_items (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, boq_item_id)     REFERENCES boq_items (tenant_id, id);
ALTER TABLE payments
  ADD FOREIGN KEY (tenant_id)  REFERENCES tenants (id),
  ADD FOREIGN KEY (voided_by)  REFERENCES users (id),
  ADD FOREIGN KEY (created_by) REFERENCES users (id),
  ADD FOREIGN KEY (tenant_id, party_id)   REFERENCES parties (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id);
ALTER TABLE allocations
  ADD FOREIGN KEY (tenant_id)  REFERENCES tenants (id),
  ADD FOREIGN KEY (created_by) REFERENCES users (id),
  ADD FOREIGN KEY (tenant_id, document_id)    REFERENCES documents (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, payment_id)     REFERENCES payments (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, credit_note_id) REFERENCES documents (tenant_id, id);
ALTER TABLE expenses
  ADD FOREIGN KEY (tenant_id)  REFERENCES tenants (id),
  ADD FOREIGN KEY (created_by) REFERENCES users (id),
  ADD FOREIGN KEY (tenant_id, project_id)      REFERENCES projects (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, vendor_party_id) REFERENCES parties (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, attachment_id)   REFERENCES attachments (tenant_id, id);
ALTER TABLE idempotency_keys
  ADD FOREIGN KEY (tenant_id) REFERENCES tenants (id),
  ADD FOREIGN KEY (user_id)   REFERENCES users (id);

-- schema.sql: id bigint GENERATED ALWAYS AS IDENTITY (Django creates BY DEFAULT).
ALTER TABLE audit_log ALTER COLUMN id SET GENERATED ALWAYS;
"""

TRIGGERS = r"""
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
    UPDATE documents SET amount_settled = amount_settled - OLD.amount WHERE id = OLD.document_id;
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'allocations are immutable; delete and re-create' USING ERRCODE = 'check_violation';
  END IF;

  SELECT doc_type, status, party_id INTO target FROM documents WHERE id = NEW.document_id;
  IF target.status <> 'ISSUED' OR target.doc_type NOT IN ('TAX_INVOICE', 'BILL_OF_SUPPLY', 'DEBIT_NOTE') THEN
    RAISE EXCEPTION 'only issued invoices, bills of supply and debit notes can be settled'
      USING ERRCODE = 'check_violation';
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

  UPDATE documents SET amount_settled = amount_settled + NEW.amount WHERE id = NEW.document_id;
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
    'payments', 'allocations', 'expenses']
  LOOP
    EXECUTE format(
      'CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION audit_row_change()', t);
  END LOOP;
END $$;
"""

ROW_LEVEL_SECURITY = r"""
-- Standard policy: a row is visible/writable only inside its own tenant.
-- FORCE makes it apply to the table owner too (defence in depth).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'gst_registrations', 'parties', 'projects', 'boq_items', 'catalog_items', 'attachments',
    'document_series', 'documents', 'document_lines', 'payments', 'allocations', 'expenses',
    'idempotency_keys']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = app_current_tenant()) '
      'WITH CHECK (tenant_id = app_current_tenant())', t);
  END LOOP;
END $$;

-- tenants: the current tenant, plus (read-only) every tenant the signed-in
-- user is an active member of — needed for the tenant switcher at login.
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
                    AND m.status = 'ACTIVE'));

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY membership_tenant ON memberships
  USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
CREATE POLICY membership_own_read ON memberships FOR SELECT
  USING (user_id = app_current_user_id());

-- audit_log: readable per tenant; rows are only ever inserted by the
-- SECURITY DEFINER trigger (owner), so RLS is enabled but not forced.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_tenant_read ON audit_log FOR SELECT
  USING (tenant_id = app_current_tenant());

-- users and auth_sessions have no tenant; the app only ever reads them by
-- primary key, email or token hash, and never lists them across tenants.
"""

VIEWS = r"""
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

CREATE VIEW v_receivables WITH (security_invoker = true) AS
SELECT
  d.tenant_id, d.id AS document_id, d.doc_type, d.doc_number, d.doc_date, d.due_date,
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
  AND d.amount_settled < d.net_receivable;

-- Retention money held by clients, per project (released later by payment).
CREATE VIEW v_project_billing WITH (security_invoker = true) AS
SELECT
  p.tenant_id, p.id AS project_id, p.code, p.name, p.contract_value,
  coalesce(sum(CASE WHEN d.doc_type = 'CREDIT_NOTE' THEN -d.subtotal ELSE d.subtotal END), 0) AS billed_taxable,
  coalesce(sum(d.retention_amount), 0)                       AS retention_held,
  coalesce(sum(d.income_tax_tds_amount + d.gst_tds_amount), 0) AS tds_deducted,
  coalesce(sum(d.advance_recovery_amount), 0)                AS advance_recovered,
  coalesce(sum(d.net_receivable - d.amount_settled) FILTER (WHERE d.doc_type <> 'CREDIT_NOTE'), 0) AS outstanding
FROM projects p
LEFT JOIN documents d
  ON d.tenant_id = p.tenant_id AND d.project_id = p.id AND d.status = 'ISSUED' AND d.is_revenue
GROUP BY p.tenant_id, p.id, p.code, p.name, p.contract_value;
"""

GRANTS = r"""
-- db/schema.sql section 10, with the table list spelled out instead of
-- ALL TABLES so that Django's own django_migrations table gets nothing.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO billing_app;

GRANT SELECT, INSERT, UPDATE ON
  users, tenants, memberships, auth_sessions, gst_registrations, parties, projects,
  boq_items, catalog_items, attachments, document_series, documents, document_lines,
  payments, allocations, expenses, idempotency_keys
  TO billing_app;
-- Audit rows are written only by the trigger; views are read-only.
GRANT SELECT ON audit_log, v_billing_summary, v_receivables, v_project_billing TO billing_app;
-- Hard deletes only where they are part of the design (drafts, unwinding
-- allocations, editable masters, housekeeping). Everything else is
-- cancelled / voided / archived instead.
GRANT DELETE ON documents, document_lines, allocations, boq_items, catalog_items,
                idempotency_keys, auth_sessions TO billing_app;
-- Settlement totals are owned by the allocations trigger.
REVOKE UPDATE ON documents FROM billing_app;
GRANT UPDATE (status, doc_type, gst_registration_id, series_id, doc_number, doc_date, due_date, valid_until,
              party_id, project_id, source_document_id, original_document_id, is_ra_bill, ra_sequence,
              supplier_snapshot, party_snapshot, place_of_supply, supply_type, reverse_charge,
              subtotal, cgst_amount, sgst_amount, igst_amount, cess_amount, round_off, grand_total,
              retention_amount, income_tax_tds_amount, gst_tds_amount, advance_recovery_amount, net_receivable,
              notes, terms, pdf_attachment_id, issued_at, issued_by, cancelled_at, cancelled_by, cancel_reason,
              version, updated_at)
  ON documents TO billing_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_initial"),
        ("accounts", "0001_initial"),
        ("audit", "0001_initial"),
        ("catalog", "0001_initial"),
        ("documents", "0001_initial"),
        ("expenses", "0001_initial"),
        ("files", "0001_initial"),
        ("parties", "0001_initial"),
        ("payments", "0001_initial"),
        ("projects", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    # Irreversible on purpose: dropping RLS or the audit trail is never a rollback.
    operations = [
        migrations.RunSQL(FOREIGN_KEYS),
        migrations.RunSQL(TRIGGERS),
        migrations.RunSQL(ROW_LEVEL_SECURITY),
        migrations.RunSQL(VIEWS),
        migrations.RunSQL(GRANTS),
    ]
