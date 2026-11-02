"""Client portal use cases (W.5b): what a client's own people can see and do.

Every function runs in a CLIENT session, where the database already limits
each table to the client's own issued rows (db/schema.sql §8, client_scope).
The explicit party filters below say the same thing in code; another
client's or another tenant's object is simply not found (404).
"""

import uuid
from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Model, QuerySet

from apps.core.errors import Conflict, Forbidden, NotFound
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.documents.models import Document
from apps.documents.services import lifecycle
from apps.parties.models import Party
from apps.payments.models import Payment
from apps.projects.models import Project
from apps.projects.services import boq_progress_rows
from apps.reminders.services import tenant_today
from apps.reports.statement import build_statement
from apps.tenants.models import Tenant

CLIENT = "CLIENT"


def _party_id(principal: Principal) -> uuid.UUID:
    if principal.role != CLIENT or principal.party_id is None:
        raise Forbidden  # views check IsClient first; services never trust that alone
    return principal.party_id


def _one[M: Model](queryset: QuerySet[M], pk: uuid.UUID) -> M:
    obj = queryset.filter(pk=pk).first()
    if obj is None:
        raise NotFound
    return obj


def me(principal: Principal) -> dict[str, Any]:
    party = get_or_404(Party, _party_id(principal))
    tenant = Tenant.objects.get(pk=principal.tenant_id)
    return {"business": tenant, "client": party}


def documents(principal: Principal) -> QuerySet[Document]:
    return (
        Document.objects.filter(party_id=_party_id(principal))
        .exclude(status="DRAFT")
        .select_related("project")
    )


def document(principal: Principal, doc_id: uuid.UUID) -> Document:
    return _one(documents(principal), doc_id)


def respond_to_quotation(
    principal: Principal, doc_id: uuid.UUID, expected: int, *, accept: bool
) -> Document:
    """The client accepts or declines a quotation sent to them, while it is
    still valid (valid_until, in the business's time zone)."""
    with transaction.atomic():
        doc = document(principal, doc_id)
        if doc.doc_type == "QUOTATION" and doc.status == "ISSUED" and doc.valid_until:
            tenant = Tenant.objects.get(pk=principal.tenant_id)
            if doc.valid_until < tenant_today(tenant.timezone):
                raise Conflict(
                    "This quotation has expired. Ask for a new one.", code="quotation_expired"
                )
        lifecycle.record_quotation_response(doc_id, expected, accept=accept)
    return document(principal, doc_id)


def payments(principal: Principal) -> QuerySet[Payment]:
    return Payment.objects.filter(party_id=_party_id(principal), status="RECORDED").select_related(
        "project"
    )


def statement(principal: Principal, start: date, end: date) -> dict[str, Any]:
    party = get_or_404(Party, _party_id(principal))
    result = build_statement(principal.tenant_id, party.pk, start, end)
    result["party"] = {"id": party.pk, "display_name": party.display_name, "gstin": party.gstin}
    return result


def projects(principal: Principal) -> QuerySet[Project]:
    return Project.objects.filter(client_party_id=_party_id(principal)).order_by("code")


def boq_progress(principal: Principal, project_id: uuid.UUID) -> dict[str, Any]:
    return boq_progress_rows(_one(projects(principal), project_id))
