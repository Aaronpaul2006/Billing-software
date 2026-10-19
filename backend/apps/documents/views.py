"""Billing document endpoints (docs/02-api-design.md §5). Drafts in Phase 1.5."""

import uuid
from typing import Any

import django_filters
from django.db.models import F, Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent

from .models import Document
from .serializers import (
    DocumentListSerializer,
    DocumentSerializer,
    DocumentWriteSerializer,
    PreviewSerializer,
    TotalsSerializer,
)
from .services import drafts

DRAFT = "documents.draft"


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Comma-separated values: ?doc_type=TAX_INVOICE,DEBIT_NOTE"""


class DocumentFilter(django_filters.FilterSet):
    doc_type = CharInFilter(field_name="doc_type", lookup_expr="in")
    status = CharInFilter(field_name="status", lookup_expr="in")
    book = django_filters.ChoiceFilter(
        choices=[("GST", "GST"), ("NON_GST", "NON_GST"), ("ALL", "ALL")], method="filter_book"
    )
    party_id = django_filters.UUIDFilter(field_name="party_id")
    project_id = django_filters.UUIDFilter(field_name="project_id")
    doc_date_from = django_filters.DateFilter(field_name="doc_date", lookup_expr="gte")
    doc_date_to = django_filters.DateFilter(field_name="doc_date", lookup_expr="lte")
    due_date_to = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    payment_state = django_filters.ChoiceFilter(
        choices=[("UNPAID", "UNPAID"), ("PARTIAL", "PARTIAL"), ("PAID", "PAID")],
        method="filter_payment_state",
    )
    q = django_filters.CharFilter(field_name="doc_number", lookup_expr="icontains")

    class Meta:
        model = Document
        fields: tuple[str, ...] = ()

    def filter_book(self, qs: QuerySet[Document], name: str, value: str) -> QuerySet[Document]:
        return qs if value == "ALL" else qs.filter(is_gst_document=(value == "GST"))

    def filter_payment_state(
        self, qs: QuerySet[Document], name: str, value: str
    ) -> QuerySet[Document]:
        if value == "UNPAID":
            return qs.filter(amount_settled=0)
        if value == "PAID":
            return qs.filter(amount_settled__gte=F("net_receivable"), net_receivable__gt=0)
        return qs.filter(Q(amount_settled__gt=0) & Q(amount_settled__lt=F("net_receivable")))


class DocumentListView(ActionAPIView):
    write_action = DRAFT
    serializer_class = DocumentListSerializer
    filterset_class = DocumentFilter
    ordering_fields = ("doc_date", "doc_number", "created_at")

    def get_queryset(self) -> Any:
        return Document.objects.all()

    @extend_schema(responses={200: DocumentListSerializer(many=True)}, tags=["documents"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), DocumentListSerializer)

    @extend_schema(
        request=DocumentWriteSerializer, responses={201: DocumentSerializer}, tags=["documents"]
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = DocumentWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        doc = drafts.create_draft(self.principal, data.validated_data)
        return detail_response(doc, DocumentSerializer, status=201)


class DocumentDetailView(ActionAPIView):
    write_action = DRAFT

    @extend_schema(responses={200: DocumentSerializer}, tags=["documents"])
    def get(self, request: Request, document_id: uuid.UUID) -> Response:
        return detail_response(drafts.get_document(self.principal, document_id), DocumentSerializer)

    @extend_schema(
        request=DocumentWriteSerializer, responses={200: DocumentSerializer}, tags=["documents"]
    )
    def patch(self, request: Request, document_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: drafts.get_document(self.principal, document_id),
            input_serializer=DocumentWriteSerializer,
            update=lambda v, changes: drafts.update_draft(self.principal, document_id, v, changes),
            output_serializer=DocumentSerializer,
        )

    @extend_schema(responses={204: None}, tags=["documents"])
    def delete(self, request: Request, document_id: uuid.UUID) -> Response:
        drafts.delete_draft(self.principal, document_id)
        return Response(status=204)


class PreviewTotalsView(ActionAPIView):
    """Live totals while the user types: nothing is saved."""

    read_action = DRAFT
    write_action = DRAFT

    @extend_schema(
        request=DocumentWriteSerializer, responses={200: PreviewSerializer}, tags=["documents"]
    )
    def post(self, request: Request) -> Response:
        data = DocumentWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        c = drafts.preview(self.principal, data.validated_data)
        lines = [
            {**{k: str(v) for k, v in out.__dict__.items()}, "line_no": i}
            for i, out in enumerate(c.out.lines, start=1)
        ]
        return Response(
            {
                "place_of_supply": c.resolved.place_of_supply,
                "supply_type": c.out.supply_type,
                "totals": TotalsSerializer(c.out).data,
                "lines": lines,
            }
        )
