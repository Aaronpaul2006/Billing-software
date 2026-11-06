"""The activity log (Part B): who changed what, and when, across the business.

Read from the audit trail the database triggers write for every change (so
nothing can skip it). Each entry names the record and the fields that changed,
never their values: values such as bank details stay on their own screens.
A bill's lines, payment allocations and measurement rows are left out: they
are rewritten with every save and the bill's own entry already says it changed.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from apps.accounts.models import User
from apps.documents.pdf.render import inr

from .models import AuditLog

# table -> (what it is called on screen, the fields that name a record)
RECORD_TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
    "documents": ("Bill or quotation", ("doc_number",)),
    "payments": ("Payment", ("reference",)),
    "expenses": ("Expense", ("description",)),
    "vendor_bills": ("Vendor bill", ("bill_number",)),
    "vendor_payments": ("Payment to a vendor", ("reference",)),
    "parties": ("Client or vendor", ("display_name",)),
    "projects": ("Project", ("name", "code")),
    "boq_items": ("BOQ item", ("item_code", "description")),
    "catalog_items": ("Catalog item", ("name",)),
    "catalog_item_variants": ("Catalog variant", ("attribute", "value")),
    "retention_releases": ("Retention release", ("reference",)),
    "tds_certificates": ("TDS certificate", ("certificate_number",)),
    "document_templates": ("Template", ("name",)),
    "payment_reminders": ("Payment reminder", ()),
    "document_emails": ("Bill emailed", ("sent_to",)),
    "exports": ("Export", ("file_name",)),
    "memberships": ("Member", ("role",)),
    "email_invitations": ("Invitation", ("email",)),
    "tenants": ("Company details", ("legal_name",)),
    "gst_registrations": ("GST registration", ("gstin",)),
    "document_series": ("Number series", ("prefix",)),
    "print_settings": ("Bill printing", ()),
    "tally_settings": ("Tally export", ()),
}

# Bookkeeping, not changes anyone made on purpose.
QUIET = {
    "updated_at",
    "version",
    "created_at",
    "pdf_key",
    "pdf_rendered_at",
    "pdf_attachment_id",  # the system made the PDF
    "last_used_at",
    "next_number",  # a number series moves on with every bill issued
}
ROLES = {
    "OWNER": "Owner",
    "ADMIN": "Admin",
    "ACCOUNTANT": "Accountant",
    "SITE_ENGINEER": "Site engineer",
    "VIEWER": "Viewer",
    "CLIENT": "Client portal user",
}

DOC_TITLES = {
    "TAX_INVOICE": "Tax invoice",
    "BILL_OF_SUPPLY": "Bill of supply",
    "QUOTATION": "Quotation",
    "PROFORMA": "Proforma invoice",
    "CREDIT_NOTE": "Credit note",
    "DEBIT_NOTE": "Debit note",
}
STATUS_WORDS = {
    "ISSUED": "issued",
    "CANCELLED": "cancelled",
    "ACCEPTED": "marked accepted",
    "DECLINED": "marked declined",
    "VOIDED": "voided",
}


def _words(field: str) -> str:
    field = field.removesuffix("_id")
    return field.replace("_", " ")


def _record(table: str, data: dict[str, Any]) -> str:
    if table == "documents":
        title = DOC_TITLES.get(str(data.get("doc_type")), "Document")
        return f"{title} {data.get('doc_number') or '(draft)'}"
    if table == "memberships":
        return ROLES.get(str(data.get("role")), "Member")
    if table in ("payments", "vendor_payments") and data.get("amount") is not None:
        paid = date.fromisoformat(str(data["payment_date"]))
        return f"₹{inr(Decimal(str(data['amount'])))} on {paid.day} {paid:%b %Y}"
    _, fields = RECORD_TYPES[table]
    parts = [str(data[f]) for f in fields if data.get(f)]
    return " ".join(parts)


def _what(row: AuditLog) -> tuple[str, list[str]]:
    """'added' / 'changed' / 'deleted' (or a status in words), and the fields changed."""
    if row.action == "INSERT":
        return "added", []
    if row.action == "DELETE":
        return "deleted", []
    old, new = row.old_data or {}, row.new_data or {}
    changed = sorted(k for k in new if k not in QUIET and old.get(k) != new.get(k))
    status = new.get("status") if "status" in changed else None
    if status in STATUS_WORDS:
        return STATUS_WORDS[str(status)], []  # the status says it; the rest follows from it
    return "changed", [_words(k) for k in changed]


def entries(rows: list[AuditLog]) -> list[dict[str, Any]]:
    """The page of audit rows, ready to show."""
    actors = {r.actor_user_id for r in rows if r.actor_user_id}
    names: dict[uuid.UUID, str] = dict(
        User.objects.filter(pk__in=actors).values_list("id", "full_name")
    )
    out = []
    for r in rows:
        data = r.new_data or r.old_data or {}
        what, fields = _what(r)
        if what == "changed" and not fields:
            continue  # only bookkeeping changed (a PDF made, a number used)
        out.append(
            {
                "id": r.pk,
                "occurred_at": r.occurred_at,
                "actor_id": r.actor_user_id,
                "actor_name": names.get(r.actor_user_id) if r.actor_user_id else None,
                "record_type": r.table_name,
                "record_type_label": RECORD_TYPES[r.table_name][0],
                "record_id": r.row_id,
                "record": _record(r.table_name, data),
                "action": what,
                "changed_fields": fields,
            }
        )
    return out
