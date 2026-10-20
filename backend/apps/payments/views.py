"""Payment endpoints (docs/02-api-design.md §6)."""

import uuid
from typing import Any

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_action
from apps.core.idempotency import idempotent

from . import services
from .models import Payment
from .serializers import (
    AllocateSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
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
