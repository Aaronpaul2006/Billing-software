"""A client's statement of account as a PDF (auto-escaped Django template,
WeasyPrint), like the document PDFs. Called inside the tenant's context."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from django.template.loader import render_to_string
from django.utils import timezone

from apps.documents.pdf.render import inr
from apps.documents.pdf.words import rupees_in_words
from apps.parties.models import Party
from apps.reports.statement import build_statement
from apps.tenants.models import GstRegistration, Tenant

from .builders import STATEMENT_KINDS, statement_stem


def _when(d: date) -> str:
    return d.strftime("%d %b %Y")


def build_context(tenant_id: uuid.UUID, params: dict[str, Any]) -> dict[str, Any]:
    party = Party.objects.get(pk=params["party_id"])
    start, end = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
    s = build_statement(tenant_id, party.pk, start, end)
    tenant = Tenant.objects.get(pk=tenant_id)
    registration = GstRegistration.objects.filter(is_default=True).first()
    closing: Decimal = s["closing_balance"]
    return {
        "company": {
            "name": tenant.legal_name,
            "trade_name": tenant.trade_name,
            "gstin": registration.gstin if registration else None,
            "address": registration.address if registration else {},
        },
        "party": party,
        "period": f"{_when(start)} to {_when(end)}",
        "made_on": _when(timezone.localdate()),
        "opening": inr(s["opening_balance"]),
        "rows": [
            {
                "date": _when(e["date"]),
                "type": STATEMENT_KINDS[e["kind"]],
                "description": e["description"],
                "debit": inr(e["debit"]) if e["debit"] else "",
                "credit": inr(e["credit"]) if e["credit"] else "",
                "balance": inr(e["balance"]),
            }
            for e in s["entries"]
        ],
        "total_debit": inr(s["total_debit"]),
        "total_credit": inr(s["total_credit"]),
        "closing": inr(abs(closing)),
        "closing_words": rupees_in_words(abs(closing)),
        "closing_side": "due from you"
        if closing > 0
        else ("paid in advance" if closing < 0 else ""),
        "stem": statement_stem(party, params),
    }


def render_html(tenant_id: uuid.UUID, params: dict[str, Any]) -> str:
    return render_to_string("exports/statement.html", build_context(tenant_id, params))


def render(tenant_id: uuid.UUID, params: dict[str, Any]) -> tuple[bytes, str, int, list[str]]:
    """(PDF bytes, file name, row count, warnings), as services.build returns."""
    from weasyprint import HTML  # Linux libraries; the worker image has them

    context = build_context(tenant_id, params)
    html = render_to_string("exports/statement.html", context)
    body: bytes = HTML(string=html).write_pdf()
    return body, f"{context['stem']}.pdf", len(context["rows"]), []
