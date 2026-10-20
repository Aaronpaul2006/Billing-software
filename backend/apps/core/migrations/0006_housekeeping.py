"""Housekeeping: purge expired idempotency keys and uploads never completed,
through owner-only policies and SECURITY DEFINER functions. Copied from
db/schema.sql §8."""

from django.db import migrations

FORWARD = r"""
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
"""

REVERSE = r"""
DROP FUNCTION purge_stale_uploads(integer);
DROP FUNCTION purge_expired_idempotency_keys();
DROP POLICY housekeeping_purge ON attachments;
DROP POLICY housekeeping_purge ON idempotency_keys;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0005_invitations"), ("files", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
