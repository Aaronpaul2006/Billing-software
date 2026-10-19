"""Projects and their Bill of Quantities (docs/02-api-design.md §4)."""

import uuid
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404, get_or_invalid
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document, DocumentLine
from apps.parties.models import Party
from apps.tenants.models import GstRegistration

from .models import BoqItem, Project

# Once a document refers to the project these decide its tax treatment.
LOCKED_ONCE_BILLED = ("client_party_id", "gst_registration_id", "site_state_code")


def _check_references(data: dict[str, Any]) -> None:
    if "client_party_id" in data:
        party = get_or_invalid(Party, data["client_party_id"], "client_party_id", label="party")
        if not party.is_customer:
            raise Invalid("client_party_id", "This party is not a customer.", code="not_a_customer")
    if "gst_registration_id" in data:
        registration = get_or_invalid(
            GstRegistration,
            data["gst_registration_id"],
            "gst_registration_id",
            label="GST registration",
        )
        if not registration.is_active:
            raise Invalid(
                "gst_registration_id", "This GST registration is inactive.", code="inactive"
            )


def _code_taken(exc: IntegrityError) -> Conflict:
    return Conflict("Another project already uses this code.", code="code_taken")


def get_project(principal: Principal, project_id: uuid.UUID) -> Project:
    require(principal, "tenant.read")
    return get_or_404(Project, project_id)


def create_project(principal: Principal, data: dict[str, Any]) -> Project:
    require(principal, "masters.edit")
    _check_references(data)
    try:
        with transaction.atomic():
            project = Project(**data, created_by_id=principal.user_id)
            project.save()
    except IntegrityError as exc:
        raise _code_taken(exc) from exc
    return project


def update_project(
    principal: Principal, project_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> Project:
    require(principal, "masters.edit")
    try:
        with transaction.atomic():
            project = get_or_404(Project, project_id, for_update=True)
            touched = [
                f for f in LOCKED_ONCE_BILLED if f in changes and changes[f] != getattr(project, f)
            ]
            if touched and Document.objects.filter(project_id=project_id).exists():
                raise Conflict(
                    f"Documents refer to this project; {', '.join(touched)} cannot change.",
                    code="project_in_use",
                )
            _check_references(changes)
            update_versioned(Project.objects, project_id, expected, **changes)
    except IntegrityError as exc:
        raise _code_taken(exc) from exc
    return get_or_404(Project, project_id)


# --- BOQ items -----------------------------------------------------------------------


def _item_code_taken() -> Conflict:
    return Conflict("This project already has an item with this code.", code="item_code_taken")


def get_boq_item(principal: Principal, item_id: uuid.UUID) -> BoqItem:
    require(principal, "tenant.read")
    return get_or_404(BoqItem, item_id)


def create_boq_item(principal: Principal, project_id: uuid.UUID, data: dict[str, Any]) -> BoqItem:
    require(principal, "boq.edit")
    project = get_or_404(Project, project_id)
    try:
        with transaction.atomic():
            item = BoqItem(**data, project=project)
            item.save()
    except IntegrityError as exc:
        raise _item_code_taken() from exc
    return item


def update_boq_item(
    principal: Principal, item_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> BoqItem:
    require(principal, "boq.edit")
    try:
        with transaction.atomic():
            get_or_404(BoqItem, item_id, for_update=True)
            update_versioned(BoqItem.objects, item_id, expected, **changes)
    except IntegrityError as exc:
        raise _item_code_taken() from exc
    return get_or_404(BoqItem, item_id)


def delete_boq_item(principal: Principal, item_id: uuid.UUID) -> None:
    require(principal, "boq.edit")
    with transaction.atomic():
        item = get_or_404(BoqItem, item_id, for_update=True)
        if DocumentLine.objects.filter(boq_item_id=item.pk).exists():
            raise Conflict(
                "This item has been billed and cannot be deleted.", code="boq_item_billed"
            )
        item.delete()
