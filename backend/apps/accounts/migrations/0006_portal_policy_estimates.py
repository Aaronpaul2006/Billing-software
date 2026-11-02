"""Client-portal policies get ordinary row estimates (W.7 speed check).

`app_current_party() IS NULL OR <scope>` was estimated at 0.5 % of rows, so
staff reports on a large company picked nested loops and took seconds.
`NOT app_portal_session() OR <scope>` (an opaque PL/pgSQL function) means the
same, with the planner's normal estimate. Copied from db/schema.sql §1, §8."""

from django.db import migrations

DROP = r"""
DROP POLICY client_scope ON gst_registrations;
DROP POLICY client_scope ON catalog_items;
DROP POLICY client_scope ON catalog_item_variants;
DROP POLICY client_scope ON document_series;
DROP POLICY client_scope ON expenses;
DROP POLICY client_scope ON tds_certificates;
DROP POLICY client_scope ON email_invitations;
DROP POLICY client_scope ON payment_reminders;
DROP POLICY client_scope ON document_templates;
DROP POLICY client_scope ON audit_log;
DROP POLICY client_scope ON parties;
DROP POLICY client_scope ON projects;
DROP POLICY client_scope ON boq_items;
DROP POLICY client_scope ON documents;
DROP POLICY client_scope ON document_lines;
DROP POLICY client_scope ON payments;
DROP POLICY client_scope ON retention_releases;
DROP POLICY client_scope ON allocations;
DROP POLICY client_scope ON attachments;
DROP POLICY client_scope ON idempotency_keys;
DROP POLICY client_scope ON exports;
DROP POLICY client_scope ON memberships;
DROP POLICY client_scope ON tenants;
"""

FORWARD = (
    DROP
    + r"""
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
    'tds_certificates', 'email_invitations', 'payment_reminders', 'document_templates', 'audit_log']
  LOOP
    EXECUTE format(
      'CREATE POLICY client_scope ON %I AS RESTRICTIVE USING (NOT app_portal_session())', t);
  END LOOP;
END $$;
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
                     WHERE d.tenant_id = attachments.tenant_id AND d.pdf_attachment_id = attachments.id));
CREATE POLICY client_scope ON idempotency_keys AS RESTRICTIVE
  USING (NOT app_portal_session() OR user_id = app_current_user_id());
CREATE POLICY client_scope ON exports AS RESTRICTIVE
  USING (NOT app_portal_session() OR requested_by = app_current_user_id());
CREATE POLICY client_scope ON memberships AS RESTRICTIVE
  USING (NOT app_portal_session() OR user_id = app_current_user_id());
-- The client may read the business's own row (its name), never change it.
CREATE POLICY client_scope ON tenants AS RESTRICTIVE FOR UPDATE
  USING (NOT app_portal_session());
"""
)

REVERSE = (
    DROP
    + r"""
DROP FUNCTION app_portal_session();

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
    'tds_certificates', 'email_invitations', 'payment_reminders', 'document_templates', 'audit_log']
  LOOP
    EXECUTE format(
      'CREATE POLICY client_scope ON %I AS RESTRICTIVE USING (app_current_party() IS NULL)', t);
  END LOOP;
END $$;
CREATE POLICY client_scope ON parties AS RESTRICTIVE
  USING (app_current_party() IS NULL OR id = app_current_party());
CREATE POLICY client_scope ON projects AS RESTRICTIVE
  USING (app_current_party() IS NULL OR client_party_id = app_current_party());
CREATE POLICY client_scope ON boq_items AS RESTRICTIVE
  USING (app_current_party() IS NULL
         OR EXISTS (SELECT 1 FROM projects p
                     WHERE p.tenant_id = boq_items.tenant_id AND p.id = boq_items.project_id));
CREATE POLICY client_scope ON documents AS RESTRICTIVE
  USING (app_current_party() IS NULL OR (party_id = app_current_party() AND status <> 'DRAFT'));
CREATE POLICY client_scope ON document_lines AS RESTRICTIVE
  USING (app_current_party() IS NULL
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = document_lines.tenant_id AND d.id = document_lines.document_id));
CREATE POLICY client_scope ON payments AS RESTRICTIVE
  USING (app_current_party() IS NULL OR (party_id = app_current_party() AND status = 'RECORDED'));
CREATE POLICY client_scope ON retention_releases AS RESTRICTIVE
  USING (app_current_party() IS NULL OR (party_id = app_current_party() AND status = 'RELEASED'));
CREATE POLICY client_scope ON allocations AS RESTRICTIVE
  USING (app_current_party() IS NULL
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = allocations.tenant_id AND d.id = allocations.document_id)
         OR EXISTS (SELECT 1 FROM retention_releases r
                     WHERE r.tenant_id = allocations.tenant_id AND r.id = allocations.retention_release_id));
CREATE POLICY client_scope ON attachments AS RESTRICTIVE
  USING (app_current_party() IS NULL
         OR EXISTS (SELECT 1 FROM documents d
                     WHERE d.tenant_id = attachments.tenant_id AND d.pdf_attachment_id = attachments.id));
CREATE POLICY client_scope ON idempotency_keys AS RESTRICTIVE
  USING (app_current_party() IS NULL OR user_id = app_current_user_id());
CREATE POLICY client_scope ON exports AS RESTRICTIVE
  USING (app_current_party() IS NULL OR requested_by = app_current_user_id());
CREATE POLICY client_scope ON memberships AS RESTRICTIVE
  USING (app_current_party() IS NULL OR user_id = app_current_user_id());
-- The client may read the business's own row (its name), never change it.
CREATE POLICY client_scope ON tenants AS RESTRICTIVE FOR UPDATE
  USING (app_current_party() IS NULL);
"""
)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_client_portal")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
