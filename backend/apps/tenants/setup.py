"""How far a new business has got with setting up (H.2): the checklist on
the first page after sign-in. One query of EXISTS checks; RLS limits each to
the current tenant, and the explicit tenant filters say so too."""

import uuid

from django.db import connection

STEPS = ("gst_registration", "number_series", "client", "project", "first_bill", "team")


def setup_status(tenant: uuid.UUID) -> dict[str, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT
                 EXISTS (SELECT 1 FROM gst_registrations WHERE tenant_id = %(t)s AND is_active),
                 EXISTS (SELECT 1 FROM document_series WHERE tenant_id = %(t)s AND is_active),
                 EXISTS (SELECT 1 FROM parties WHERE tenant_id = %(t)s AND is_customer),
                 EXISTS (SELECT 1 FROM projects WHERE tenant_id = %(t)s),
                 EXISTS (SELECT 1 FROM documents WHERE tenant_id = %(t)s AND status <> 'DRAFT'),
                 (SELECT count(*) FROM memberships
                   WHERE tenant_id = %(t)s AND party_id IS NULL
                     AND status IN ('ACTIVE', 'INVITED')) > 1""",
            {"t": tenant},
        )
        row = cursor.fetchone() or ()  # one row, always
    steps = dict(zip(STEPS, (bool(v) for v in row), strict=True))
    return {**steps, "complete": all(steps.values())}
