"""Payment endpoints (docs/02-api-design.md §6)."""

import uuid
from decimal import Decimal
from typing import Any

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_action
from apps.core.idempotency import idempotent

from . import retention, services
from .models import Payment, RetentionRelease
from .serializers import (
    AllocateSerializer,
    CancelReleaseSerializer,
    DocumentAllocationsSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    ProjectRetentionSerializer,
    ReleaseCreateSerializer,
    RetentionReleaseDetailSerializer,
    RetentionReleaseSerializer,
    VoidSerializer,
)

RECORD = "payments.record"


class PaymentFilter(django_filters.FilterSet):
    party_id = django_filters.UUIDFilter(field_name="party_id")
    project_id = django_filters.UUIDFilter(field_name="project_id")
    payment_date_from = django_filters.DateFilter(field_name="payment_date", lookup_expr="gte")
    payment_date_to = django_filters.DateFilter(field_name="payment_date", lookup_expr="lte")

    class Meta:
        model = Payment
        fields = ("mode", "status")


class PaymentListView(ActionAPIView):
    write_action = RECORD
    serializer_class = PaymentSerializer
    filterset_class = PaymentFilter
    ordering_fields = ("payment_date", "amount")

    def get_queryset(self) -> Any:
        return Payment.objects.all()

    @extend_schema(responses={200: PaymentSerializer(many=True)}, tags=["payments"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), PaymentSerializer)

    @extend_schema(
        request=PaymentCreateSerializer, responses={201: PaymentSerializer}, tags=["payments"]
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = PaymentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = services.record_payment(self.principal, dict(data.validated_data))
        return detail_response(payment, PaymentSerializer, status=201)


class PaymentDetailView(ActionAPIView):
    write_action = RECORD

    @extend_schema(responses={200: PaymentSerializer}, tags=["payments"])
    def get(self, request: Request, payment_id: uuid.UUID) -> Response:
        payment = services.get_payment(self.principal, payment_id)
        return detail_response(payment, PaymentSerializer)


class PaymentAllocationsView(ActionAPIView):
    write_action = RECORD

    @extend_schema(
        request=AllocateSerializer, responses={200: PaymentSerializer}, tags=["payments"]
    )
    @idempotent
    def post(self, request: Request, payment_id: uuid.UUID) -> Response:
        data = AllocateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = services.allocate(self.principal, payment_id, data.validated_data["allocations"])
        return detail_response(payment, PaymentSerializer)


class PaymentVoidView(ActionAPIView):
    read_action = RECORD
    write_action = RECORD

    @extend_schema(request=VoidSerializer, responses={200: PaymentSerializer}, tags=["payments"])
    def post(self, request: Request, payment_id: uuid.UUID) -> Response:
        data = VoidSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return versioned_action(
            request,
            load=lambda: services.get_payment(self.principal, payment_id),
            run=lambda v: services.void_payment(
                self.principal, payment_id, v, data.validated_data["reason"]
            ),
            output_serializer=PaymentSerializer,
        )


class AllocationDetailView(ActionAPIView):
    read_action = RECORD
    write_action = RECORD

    @extend_schema(responses={204: None}, tags=["payments"])
    def delete(self, request: Request, allocation_id: uuid.UUID) -> Response:
        services.unwind(self.principal, allocation_id)
        return Response(status=204)


class DocumentAllocationsView(ActionAPIView):
    """GET: what settled a document (payments, credit notes) or, for a credit
    note, what it was applied to. POST: apply an issued credit note."""

    write_action = RECORD

    def _body(self, document_id: uuid.UUID) -> dict[str, Any]:
        doc, rows = services.document_allocations(self.principal, document_id)
        applied = None
        if doc.doc_type == "CREDIT_NOTE":
            applied = sum((a.amount for a in rows if a.credit_note_id == doc.pk), Decimal("0.00"))
        return {
            "document_id": doc.pk,
            "doc_type": doc.doc_type,
            "applied": applied,
            "unapplied": doc.grand_total - applied if applied is not None else None,
            "allocations": rows,
        }

    @extend_schema(responses={200: DocumentAllocationsSerializer}, tags=["payments"])
    def get(self, request: Request, document_id: uuid.UUID) -> Response:
        return Response(DocumentAllocationsSerializer(self._body(document_id)).data)

    @extend_schema(
        request=AllocateSerializer,
        responses={200: DocumentAllocationsSerializer},
        tags=["payments"],
    )
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        data = AllocateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.apply_credit_note(self.principal, document_id, data.validated_data["allocations"])
        return Response(DocumentAllocationsSerializer(self._body(document_id)).data)


# --- retention releases (Phase 3.3) ------------------------------------------------------

ISSUE = "documents.issue"


class ReleaseFilter(django_filters.FilterSet):
    project_id = django_filters.UUIDFilter(field_name="project_id")
    party_id = django_filters.UUIDFilter(field_name="party_id")
    release_date_from = django_filters.DateFilter(field_name="release_date", lookup_expr="gte")
    release_date_to = django_filters.DateFilter(field_name="release_date", lookup_expr="lte")

    class Meta:
        model = RetentionRelease
        fields = ("status", "book")


class RetentionReleaseListView(ActionAPIView):
    write_action = ISSUE
    serializer_class = RetentionReleaseSerializer
    filterset_class = ReleaseFilter
    ordering_fields = ("release_date", "amount")

    def get_queryset(self) -> Any:
        return RetentionRelease.objects.all()

    @extend_schema(responses={200: RetentionReleaseSerializer(many=True)}, tags=["payments"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), RetentionReleaseSerializer)

    @extend_schema(
        request=ReleaseCreateSerializer,
        responses={201: RetentionReleaseDetailSerializer},
        tags=["payments"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = ReleaseCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = retention.release(self.principal, dict(data.validated_data))
        return detail_response(row, RetentionReleaseDetailSerializer, status=201)


class RetentionReleaseDetailView(ActionAPIView):
    write_action = ISSUE

    @extend_schema(responses={200: RetentionReleaseDetailSerializer}, tags=["payments"])
    def get(self, request: Request, release_id: uuid.UUID) -> Response:
        row = retention.get_release(self.principal, release_id)
        return detail_response(row, RetentionReleaseDetailSerializer)


class RetentionReleaseCancelView(ActionAPIView):
    read_action = ISSUE
    write_action = ISSUE

    @extend_schema(
        request=CancelReleaseSerializer,
        responses={200: RetentionReleaseDetailSerializer},
        tags=["payments"],
    )
    @idempotent
    def post(self, request: Request, release_id: uuid.UUID) -> Response:
        data = CancelReleaseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return versioned_action(
            request,
            load=lambda: retention.get_release(self.principal, release_id),
            run=lambda v: retention.cancel_release(
                self.principal, release_id, v, data.validated_data["reason"]
            ),
            output_serializer=RetentionReleaseDetailSerializer,
        )


class ProjectRetentionView(ActionAPIView):
    @extend_schema(responses={200: ProjectRetentionSerializer}, tags=["payments"])
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        held = retention.project_retention(self.principal, project_id)
        return Response(
            ProjectRetentionSerializer(
                {
                    "project_id": project_id,
                    **{
                        book: {
                            "deducted": p.deducted,
                            "released": p.released,
                            "available": p.available,
                        }
                        for book, p in held.items()
                    },
                }
            ).data
        )
