"""Tally ledger names (B.16): what the Tally export writes on each voucher.

One row per business, made on the first save; until then everyone sees the
defaults at version 1, so the first save sends `If-Match: "v1"`.
"""

import uuid
from typing import Any

from django.db import transaction

from apps.core.permissions import require
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned

from .models import TALLY_LEDGERS, TallySettings


def current(tenant_id: uuid.UUID) -> TallySettings:
    """The saved names, or the defaults (not saved). Inside tenant context."""
    found = TallySettings.objects.filter(tenant_id=tenant_id).first()
    return found if found is not None else TallySettings(tenant_id=tenant_id, **TALLY_LEDGERS)


def get_tally_settings(principal: Principal) -> TallySettings:
    require(principal, "tenant.read")
    return current(principal.tenant_id)


def update_tally_settings(
    principal: Principal, expected: int, changes: dict[str, Any]
) -> TallySettings:
    require(principal, "tenant.settings")
    with transaction.atomic():
        row, _ = TallySettings.objects.get_or_create(tenant_id=principal.tenant_id)
        update_versioned(TallySettings.objects, row.pk, expected, **changes)
    return current(principal.tenant_id)


def ledgers(tenant_id: uuid.UUID) -> dict[str, str]:
    s = current(tenant_id)
    return {name: str(getattr(s, name)) for name in TALLY_LEDGERS}
