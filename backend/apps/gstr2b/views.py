"""GSTR-2B endpoints (Part B; docs/02-api-design.md)."""

import uuid
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, list_response
from apps.core.errors import Invalid
from apps.core.idempotency import idempotent
from apps.core.queries import get_or_404

from . import reader, reconcile, services
from .models import Gstr2bReturn
from .serializers import (
    Gstr2bReturnSerializer,
    ReconciliationSerializer,
    ReconQuerySerializer,
    UploadSerializer,
)

VIEW = "reports.view"


class Gstr2bReturnListView(ActionAPIView):
    """The months uploaded, newest first; upload a GSTR-2B JSON."""

    read_action = VIEW
    write_action = services.UPLOAD
    parser_classes = (MultiPartParser,)
    serializer_class = Gstr2bReturnSerializer
    ordering_fields = ("period",)

    def get_queryset(self) -> Any:
        return Gstr2bReturn.objects.select_related("gst_registration", "created_by").order_by(
            "-period"
        )

    @extend_schema(responses={200: Gstr2bReturnSerializer(many=True)}, tags=["gst"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), Gstr2bReturnSerializer)

    @extend_schema(
        request={"multipart/form-data": UploadSerializer},
        responses={201: Gstr2bReturnSerializer},
        tags=["gst"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = UploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        upload = data.validated_data["file"]
        if upload.size > reader.MAX_BYTES:
            raise Invalid("file", "At most 20 MB per upload.", code="file_too_large")
        gst_return = services.upload(self.principal, bytes(upload.read()), upload.name)
        return Response(Gstr2bReturnSerializer(gst_return).data, status=201)


def _portal(row: reconcile.Row) -> dict[str, Any] | None:
    line = row.line
    if line is None:
        return None
    return {
        "id": line.pk,
        "section": line.section,
        "doc_type": line.doc_type,
        "doc_number": line.doc_number,
        "original_number": line.original_number,
        "doc_date": line.doc_date,
        "taxable_value": line.taxable_value,
        "tax": reconcile.line_tax(line),
        "itc_available": line.itc_available,
        "itc_reason": line.itc_reason,
        "reverse_charge": line.reverse_charge,
    }


def _books(row: reconcile.Row) -> dict[str, Any] | None:
    b = row.book
    if b is None:
        return None
    return {
        "kind": b.kind,
        "id": b.id,
        "number": b.number,
        "doc_date": b.doc_date,
        "taxable_value": b.taxable_value,
        "tax": b.tax,
        "itc_eligible": b.itc_eligible,
    }


def _supplier(row: reconcile.Row) -> tuple[str, str]:
    if row.line is not None:
        name = row.line.supplier_name or (row.book.supplier_name if row.book else "")
        return row.line.supplier_gstin, name
    if row.book is not None:
        return row.book.supplier_gstin, row.book.supplier_name
    return "", ""


class ReconciliationView(ActionAPIView):
    """The GSTR-2B against the books, worked out now (reconcile.py)."""

    read_action = VIEW
    write_action = VIEW
    pagination_class = None
    filter_backends = ()

    @extend_schema(
        parameters=[ReconQuerySerializer],
        responses={200: ReconciliationSerializer},
        tags=["gst"],
    )
    def get(self, request: Request, return_id: uuid.UUID) -> Response:
        params = ReconQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        gst_return = get_or_404(Gstr2bReturn, return_id)
        result = reconcile.reconcile(gst_return)
        wanted = params.validated_data.get("status")
        rows = [
            {
                "status": row.status,
                "supplier_gstin": _supplier(row)[0],
                "supplier_name": _supplier(row)[1],
                "portal": _portal(row),
                "books": _books(row),
                "taxable_difference": row.taxable_difference,
                "tax_difference": row.tax_difference,
                "note": row.note,
            }
            for row in result.rows
            if wanted is None or row.status == wanted
        ]
        c = result.counts
        body = {
            "return_": gst_return,
            "summary": {
                "matched": c.get("MATCHED", 0),
                "amounts_differ": c.get("AMOUNTS_DIFFER", 0),
                "not_in_books": c.get("NOT_IN_BOOKS", 0),
                "not_in_2b": c.get("NOT_IN_2B", 0),
                "itc_in_2b": result.itc_in_2b,
                "itc_matched": result.itc_matched,
                "itc_not_in_books": result.itc_not_in_books,
                "itc_at_risk": result.itc_at_risk,
            },
            "rows": rows,
        }
        return Response(ReconciliationSerializer(body).data)
