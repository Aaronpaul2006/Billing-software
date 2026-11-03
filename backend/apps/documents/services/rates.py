"""The rate last charged to a client for each catalog item (B.8).

From the client's issued tax invoices and bills of supply (not cancelled
ones, not quotations or notes): per catalog item and variant, the line on the
latest bill. One query (DISTINCT ON), using the lines' index by item.
"""

import uuid
from typing import Any

from apps.core.permissions import require
from apps.core.queries import get_or_404
from apps.core.tenancy import Principal
from apps.parties.models import Party

from ..models import DocumentLine

CHARGED_TYPES = ("TAX_INVOICE", "BILL_OF_SUPPLY")


def last_rates(principal: Principal, party_id: uuid.UUID) -> list[dict[str, Any]]:
    require(principal, "tenant.read")
    party = get_or_404(Party, party_id)  # another tenant's client: 404
    rows = (
        DocumentLine.objects.filter(
            document__party_id=party.pk,
            document__status="ISSUED",
            document__doc_type__in=CHARGED_TYPES,
            catalog_item_id__isnull=False,
        )
        .order_by(
            "catalog_item_id",
            "catalog_variant_id",
            "-document__doc_date",
            "-document__issued_at",
            "-line_no",
        )
        .distinct("catalog_item_id", "catalog_variant_id")
        .values(
            "catalog_item_id",
            "catalog_variant_id",
            "rate",
            "document_id",
            "document__doc_number",
            "document__doc_date",
        )
    )
    return [
        {
            "catalog_item_id": r["catalog_item_id"],
            "catalog_variant_id": r["catalog_variant_id"],
            "rate": r["rate"],
            "document_id": r["document_id"],
            "doc_number": r["document__doc_number"],
            "doc_date": r["document__doc_date"],
        }
        for r in rows
    ]
