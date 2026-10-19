"""Parties: customers, vendors and subcontractors (docs/02-api-design.md §4).

Never deleted: archive with is_active = false.
"""

import uuid
from typing import Any

from django.db import transaction

from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned

from .models import Party


def get_party(principal: Principal, party_id: uuid.UUID) -> Party:
    require(principal, "tenant.read")
    return get_or_404(Party, party_id)


def create_party(principal: Principal, data: dict[str, Any]) -> Party:
    require(principal, "masters.edit")
    party = Party(**data, created_by_id=principal.user_id)
    party.save()
    return party


def update_party(
    principal: Principal, party_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> Party:
    require(principal, "masters.edit")
    with transaction.atomic():
        get_or_404(Party, party_id, for_update=True)
        update_versioned(Party.objects, party_id, expected, **changes)
    return get_or_404(Party, party_id)
