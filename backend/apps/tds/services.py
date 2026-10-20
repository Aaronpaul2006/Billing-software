"""TDS certificates from clients (Phase 3.4, docs/02-api-design.md §6)."""

import uuid
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.parties.models import Party

from .models import TdsCertificate

RECORD = "payments.record"


def _check_party(party_id: uuid.UUID) -> None:
    party = get_or_invalid(Party, party_id, "party_id", label="party")
    if not party.is_customer:
        raise Invalid("party_id", "TDS certificates come from customers.", code="not_a_customer")


def _number_taken() -> Conflict:
    return Conflict(
        "A certificate with this number from this TAN is already recorded.",
        code="certificate_exists",
    )


def get_certificate(principal: Principal, certificate_id: uuid.UUID) -> TdsCertificate:
    require(principal, "tenant.read")
    return get_or_404(TdsCertificate, certificate_id)


def create_certificate(principal: Principal, data: dict[str, Any]) -> TdsCertificate:
    require(principal, RECORD)
    _check_party(data["party_id"])
    try:
        with transaction.atomic():
            row = TdsCertificate(**data, created_by_id=principal.user_id)
            row.save()
    except IntegrityError as exc:
        raise _number_taken() from exc
    return get_or_404(TdsCertificate, row.pk)


def update_certificate(
    principal: Principal, certificate_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> TdsCertificate:
    require(principal, RECORD)
    if "party_id" in changes:
        _check_party(changes["party_id"])
    try:
        with transaction.atomic():
            get_or_404(TdsCertificate, certificate_id, for_update=True)
            update_versioned(TdsCertificate.objects, certificate_id, expected, **changes)
    except IntegrityError as exc:
        raise _number_taken() from exc
    return get_or_404(TdsCertificate, certificate_id)


def delete_certificate(principal: Principal, certificate_id: uuid.UUID) -> None:
    """A certificate records the client's paper: a wrong entry may be deleted (audited)."""
    require(principal, RECORD)
    with transaction.atomic():
        get_or_404(TdsCertificate, certificate_id, for_update=True).delete()
