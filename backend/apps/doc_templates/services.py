"""Quotation (and bill) templates (W.3): save a document's lines under a
name, then start new drafts from it. A draft made from a template goes
through documents.services.drafts like a typed one, so place of supply, GST,
totals and every draft rule apply; the template only supplies the lines."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import Conflict, Invalid
from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.core.versioning import update_versioned
from apps.documents.models import Document, DocumentLine
from apps.documents.serializers import DocumentWriteSerializer
from apps.documents.services import drafts

from .models import TEMPLATE_TYPES, DocumentTemplate

EDIT = "masters.edit"


def _json_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decimals as strings (JSON), exactly as entered: never through float."""
    return [
        {
            "description": line["description"],
            "sac_hsn": line.get("sac_hsn"),
            "unit": line.get("unit"),
            "quantity": str(line["quantity"]),
            "rate": str(line["rate"]),
            "discount_amount": str(line.get("discount_amount") or Decimal("0.00")),
            "discount_pct": None if line.get("discount_pct") is None else str(line["discount_pct"]),
            "gst_rate": str(line["gst_rate"]),
        }
        for line in lines
    ]


def _name_taken() -> Conflict:
    return Conflict("A template with this name already exists.", code="template_name_taken")


def get_template(principal: Principal, template_id: uuid.UUID) -> DocumentTemplate:
    require(principal, "tenant.read")
    return get_or_404(DocumentTemplate, template_id)


def create_template(principal: Principal, data: dict[str, Any]) -> DocumentTemplate:
    require(principal, EDIT)
    try:
        with transaction.atomic():
            template = DocumentTemplate(
                **{**data, "lines": _json_lines(data["lines"])},
                created_by_id=principal.user_id,
            )
            template.save()
    except IntegrityError as exc:
        raise _name_taken() from exc
    return template


def update_template(
    principal: Principal, template_id: uuid.UUID, expected: int, changes: dict[str, Any]
) -> DocumentTemplate:
    require(principal, EDIT)
    if "lines" in changes:
        changes = {**changes, "lines": _json_lines(changes["lines"])}
    try:
        with transaction.atomic():
            get_or_404(DocumentTemplate, template_id, for_update=True)
            update_versioned(DocumentTemplate.objects, template_id, expected, **changes)
    except IntegrityError as exc:
        raise _name_taken() from exc
    return get_or_404(DocumentTemplate, template_id)


def delete_template(principal: Principal, template_id: uuid.UUID) -> None:
    require(principal, EDIT)
    with transaction.atomic():
        get_or_404(DocumentTemplate, template_id, for_update=True).delete()


def save_document_as_template(
    principal: Principal, document_id: uuid.UUID, name: str, valid_days: int | None
) -> DocumentTemplate:
    """Copy a document's lines (BOQ lines become plain lines: a BOQ belongs to one project)."""
    require(principal, EDIT)
    doc = get_or_404(Document, document_id)
    if doc.doc_type not in TEMPLATE_TYPES:
        raise Conflict("Credit and debit notes cannot be templates.", code="not_templatable")
    if valid_days and doc.doc_type != "QUOTATION":
        raise Invalid("valid_days", "Only quotations have a validity.", code="not_allowed")
    lines = [
        {
            "description": line.description,
            "sac_hsn": line.sac_hsn,
            "unit": line.unit,
            "quantity": line.quantity,
            "rate": line.rate,
            "discount_amount": line.discount_amount,
            "discount_pct": line.discount_pct,
            "gst_rate": line.gst_rate,
        }
        for line in DocumentLine.objects.filter(document_id=doc.pk).order_by("line_no")
    ]
    if not lines:
        raise Conflict("This document has no lines to keep.", code="no_lines")
    if valid_days is None and doc.doc_type == "QUOTATION" and doc.valid_until:
        valid_days = max(1, min(365, (doc.valid_until - doc.doc_date).days))
    return create_template(
        principal,
        {
            "name": name,
            "doc_type": doc.doc_type,
            "valid_days": valid_days,
            "notes": doc.notes,
            "terms": doc.terms,
            "lines": lines,
        },
    )


def use_template(principal: Principal, template_id: uuid.UUID, data: dict[str, Any]) -> Document:
    """A new draft from the template, for `party_id` (and `project_id`) on `doc_date`."""
    require(principal, "documents.draft")
    template = get_or_404(DocumentTemplate, template_id)
    body: dict[str, Any] = {
        "doc_type": template.doc_type,
        "party_id": str(data["party_id"]),
        "project_id": str(data["project_id"]) if data.get("project_id") else None,
        "doc_date": data["doc_date"].isoformat(),
        "notes": template.notes,
        "terms": template.terms,
        "lines": [{k: v for k, v in line.items() if v is not None} for line in template.lines],
    }
    if template.doc_type == "QUOTATION" and template.valid_days:
        body["valid_until"] = (data["doc_date"] + timedelta(days=template.valid_days)).isoformat()
    write = DocumentWriteSerializer(data=body)
    write.is_valid(raise_exception=True)  # the same checks as a typed draft
    return drafts.create_draft(principal, dict(write.validated_data))
