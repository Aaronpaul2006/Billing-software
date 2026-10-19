"""Invitations: invitees may read the inviting tenant's row, and accept or
decline through respond_to_invitation(). Copied from db/schema.sql §8."""

from django.db import migrations

FORWARD = r"""
DROP POLICY tenant_member_read ON tenants;
CREATE POLICY tenant_member_read ON tenants FOR SELECT
  USING (EXISTS (SELECT 1 FROM memberships m
                  WHERE m.tenant_id = tenants.id
                    AND m.user_id = app_current_user_id()
                    AND m.status IN ('ACTIVE', 'INVITED')));

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
"""

REVERSE = r"""
DROP FUNCTION respond_to_invitation(uuid, boolean);
DROP POLICY tenant_member_read ON tenants;
CREATE POLICY tenant_member_read ON tenants FOR SELECT
  USING (EXISTS (SELECT 1 FROM memberships m
                  WHERE m.tenant_id = tenants.id
                    AND m.user_id = app_current_user_id()
                    AND m.status = 'ACTIVE'));
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0004_app_reads_migration_history")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
