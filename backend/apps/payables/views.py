"""Payables endpoints (Part B; docs/02-api-design.md §6)."""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

import django_filters
from django.db.models import F, Prefetch, QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import (
    ActionAPIView,
    detail_response,
    list_response,
    versioned_action,
    versioned_patch,
)
from apps.core.idempotency import idempotent
from apps.core.queries import get_or_404, get_or_invalid
from apps.parties.models import Party
from apps.payments.serializers import VoidSerializer

from . import services, tds
from .models import VendorAllocation, VendorBill, VendorPayment
from .serializers import (
    PayablesSerializer,
    TdsQuerySerializer,
    TdsSuggestionSerializer,
    VendorBillSerializer,
    VendorBillWriteSerializer,
    VendorPaymentCreateSerializer,
    VendorPaymentSerializer,
)

RECORD = "payments.record"


class VendorBillFilter(django_filters.FilterSet):
    vendor_party_id = django_filters.UUIDFilter(field_name="vendor_party_id")
    project_id = django_filters.UUIDFilter(field_name="project_id")
    bill_date_from = django_filters.DateFilter(field_name="bill_date", lookup_expr="gte")
    bill_date_to = django_filters.DateFilter(field_name="bill_date", lookup_expr="lte")
    payment_state = django_filters.ChoiceFilter(
        choices=[("UNPAID", "UNPAID"), ("PARTIAL", "PARTIAL"), ("PAID", "PAID"), ("OPEN", "OPEN")],
        method="filter_payment_state",
    )
    q = django_filters.CharFilter(method="filter_q")

    class Meta:
        model = VendorBill
        fields = ("status", "category")

    def filter_payment_state(
        self, qs: QuerySet[VendorBill], name: str, value: str
    ) -> QuerySet[VendorBill]:
        if value == "UNPAID":
            return qs.filter(amount_paid=0, net_payable__gt=0)
        if value == "PAID":
            return qs.filter(amount_paid__gte=F("net_payable"))
        if value == "OPEN":
            return qs.filter(amount_paid__lt=F("net_payable"))
        return qs.filter(amount_paid__gt=0, amount_paid__lt=F("net_payable"))

    def filter_q(self, qs: QuerySet[VendorBill], name: str, value: str) -> QuerySet[VendorBill]:
        return qs.filter(bill_number__icontains=value) | qs.filter(
            vendor_party__display_name__icontains=value
        )


class VendorBillListView(ActionAPIView):
    write_action = RECORD
    serializer_class = VendorBillSerializer
    filterset_class = VendorBillFilter
    ordering_fields = ("bill_date", "due_date", "total_amount")

    def get_queryset(self) -> Any:
        return VendorBill.objects.select_related("vendor_party", "project")

    @extend_schema(responses={200: VendorBillSerializer(many=True)}, tags=["payables"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), VendorBillSerializer)

    @extend_schema(
        request=VendorBillWriteSerializer, responses={201: VendorBillSerializer}, tags=["payables"]
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = VendorBillWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        bill = services.record_bill(self.principal, dict(data.validated_data))
        return detail_response(bill, VendorBillSerializer, status=201)


class VendorBillDetailView(ActionAPIView):
    write_action = RECORD

    @extend_schema(responses={200: VendorBillSerializer}, tags=["payables"])
    def get(self, request: Request, bill_id: uuid.UUID) -> Response:
        return detail_response(get_or_404(VendorBill, bill_id), VendorBillSerializer)

    @extend_schema(
        request=VendorBillWriteSerializer, responses={200: VendorBillSerializer}, tags=["payables"]
    )
    def patch(self, request: Request, bill_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: get_or_404(VendorBill, bill_id),
            input_serializer=VendorBillWriteSerializer,
            update=lambda v, changes: services.update_bill(self.principal, bill_id, v, changes),
            output_serializer=VendorBillSerializer,
        )


class VendorBillVoidView(ActionAPIView):
    read_action = RECORD
    write_action = RECORD

    @extend_schema(request=VoidSerializer, responses={200: VendorBillSerializer}, tags=["payables"])
    def post(self, request: Request, bill_id: uuid.UUID) -> Response:
        data = VoidSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return versioned_action(
            request,
            load=lambda: get_or_404(VendorBill, bill_id),
            run=lambda v: services.void_bill(
                self.principal, bill_id, v, data.validated_data["reason"]
            ),
            output_serializer=VendorBillSerializer,
        )


class TdsSuggestionView(ActionAPIView):
    """What TDS to deduct on a new vendor bill, and why (rates: tds_rates.json)."""

    read_action = RECORD
    pagination_class = None
    filter_backends = ()

    @extend_schema(
        parameters=[TdsQuerySerializer],
        responses={200: TdsSuggestionSerializer},
        tags=["payables"],
    )
    def get(self, request: Request) -> Response:
        params = TdsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        q = params.validated_data
        vendor = get_or_invalid(Party, q["vendor_party_id"], "vendor_party_id", label="vendor")
        s = tds.suggest(
            vendor, q["category"], q["taxable_value"], q["bill_date"], q.get("vendor_bill_id")
        )
        return Response(TdsSuggestionSerializer(s).data)


class VendorPaymentFilter(django_filters.FilterSet):
    vendor_party_id = django_filters.UUIDFilter(field_name="vendor_party_id")
    project_id = django_filters.UUIDFilter(field_name="project_id")
    payment_date_from = django_filters.DateFilter(field_name="payment_date", lookup_expr="gte")
    payment_date_to = django_filters.DateFilter(field_name="payment_date", lookup_expr="lte")

    class Meta:
        model = VendorPayment
        fields = ("mode", "status")


def _payments() -> Any:
    return VendorPayment.objects.select_related("vendor_party", "project").prefetch_related(
        Prefetch("allocations", queryset=VendorAllocation.objects.select_related("vendor_bill"))
    )


class VendorPaymentListView(ActionAPIView):
    write_action = RECORD
    serializer_class = VendorPaymentSerializer
    filterset_class = VendorPaymentFilter
    ordering_fields = ("payment_date", "amount")

    def get_queryset(self) -> Any:
        return _payments()

    @extend_schema(responses={200: VendorPaymentSerializer(many=True)}, tags=["payables"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), VendorPaymentSerializer)

    @extend_schema(
        request=VendorPaymentCreateSerializer,
        responses={201: VendorPaymentSerializer},
        tags=["payables"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = VendorPaymentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = services.record_payment(self.principal, dict(data.validated_data))
        return detail_response(_payments().get(pk=payment.pk), VendorPaymentSerializer, status=201)


class VendorPaymentDetailView(ActionAPIView):
    write_action = RECORD

    @extend_schema(responses={200: VendorPaymentSerializer}, tags=["payables"])
    def get(self, request: Request, payment_id: uuid.UUID) -> Response:
        get_or_404(VendorPayment, payment_id)
        return detail_response(_payments().get(pk=payment_id), VendorPaymentSerializer)


class VendorPaymentVoidView(ActionAPIView):
    read_action = RECORD
    write_action = RECORD

    @extend_schema(
        request=VoidSerializer, responses={200: VendorPaymentSerializer}, tags=["payables"]
    )
    def post(self, request: Request, payment_id: uuid.UUID) -> Response:
        data = VoidSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return versioned_action(
            request,
            load=lambda: _payments().get(pk=get_or_404(VendorPayment, payment_id).pk),
            run=lambda v: _payments().get(
                pk=services.void_payment(
                    self.principal, payment_id, v, data.validated_data["reason"]
                ).pk
            ),
            output_serializer=VendorPaymentSerializer,
        )


BUCKETS = ("not_due", "days_1_30", "days_31_60", "days_61_90", "days_90_plus")


def _bucket(days_late: int) -> str:
    if days_late <= 0:
        return "not_due"
    if days_late <= 30:
        return "days_1_30"
    if days_late <= 60:
        return "days_31_60"
    if days_late <= 90:
        return "days_61_90"
    return "days_90_plus"


class PayablesReportView(ActionAPIView):
    """What we owe each vendor today, by how long it is past due (Part B)."""

    read_action = "reports.view"
    write_action = "reports.view"
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: PayablesSerializer}, tags=["reports"])
    def get(self, request: Request) -> Response:
        today = timezone.localdate()
        bills = (
            VendorBill.objects.filter(status="RECORDED", amount_paid__lt=F("net_payable"))
            .select_related("vendor_party")
            .order_by("vendor_party__display_name")
        )
        zero = Decimal("0.00")
        rows: dict[uuid.UUID, dict[str, Any]] = {}
        totals: dict[str, Any] = defaultdict(lambda: zero)
        for b in bills:
            row = rows.setdefault(
                b.vendor_party_id,
                {
                    "party_id": b.vendor_party_id,
                    "display_name": b.vendor_party.display_name,
                    "bill_count": 0,
                    **dict.fromkeys(BUCKETS, zero),
                    "total": zero,
                },
            )
            owed = b.net_payable - b.amount_paid
            key = _bucket((today - (b.due_date or b.bill_date)).days)
            row["bill_count"] += 1
            row[key] += owed
            row["total"] += owed
            totals[key] += owed
            totals["total"] += owed
            totals["bill_count"] += 1
        results = sorted(rows.values(), key=lambda r: r["total"], reverse=True)
        all_row = {
            "party_id": uuid.UUID(int=0),
            "display_name": "All vendors",
            "bill_count": int(totals["bill_count"]),
            **{k: totals[k] for k in BUCKETS},
            "total": totals["total"],
        }
        return Response(
            PayablesSerializer({"as_of": today, "results": results, "totals": all_row}).data
        )
