"""Extensions and request-context functions. Copied from db/schema.sql §1.

Runs before any table: documents.fy_start_year is a generated column that
calls fy_start_year(), and users/parties use citext.
"""

from django.db import migrations

FORWARD = r"""
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The API sets these per transaction with set_config(..., is_local => true)
-- (i.e. SET LOCAL), so they can never leak to the next request that reuses
-- a pooled connection. Unset → NULL → RLS matches no rows (fail closed).
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
"""

REVERSE = r"""
DROP FUNCTION fy_start_year(date);
DROP FUNCTION app_current_user_id();
DROP FUNCTION app_current_tenant();
"""


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = []

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
