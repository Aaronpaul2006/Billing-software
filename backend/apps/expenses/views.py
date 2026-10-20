"""Expense endpoints (docs/02-api-design.md §6)."""

import uuid
from typing import Any

import django_filters
from django.db.models import F, Q, QuerySet
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

from . import services
from .models import Expense
from .serializers import ExpenseSerializer, ExpenseWriteSerializer

RECORD = "expenses.record"


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """?category=MATERIAL,LABOUR"""


class ExpenseFilter(django_filters.FilterSet):
    category = CharInFilter(field_name="category", lookup_expr="in")
    project_id = django_filters.UUIDFilter(field_name="project_id")
    vendor_party_id = django_filters.UUIDFilter(field_name="vendor_party_id")
    expense_date_from = django_filters.DateFilter(field_name="expense_date", lookup_expr="gte")
    expense_date_to = django_filters.DateFilter(field_name="expense_date", lookup_expr="lte")
    payment_state = django_filters.ChoiceFilter(
        choices=[("UNPAID", "UNPAID"), ("PARTIAL", "PARTIAL"), ("PAID", "PAID")],
        method="filter_payment_state",
    )

    class Meta:
        model = Expense
        fields = ("status",)

    def filter_payment_state(
        self, qs: QuerySet[Expense], name: str, value: str
    ) -> QuerySet[Expense]:
        if value == "UNPAID":
            return qs.filter(amount_paid=0, total_amount__gt=0)
        if value == "PAID":
            return qs.filter(amount_paid__gte=F("total_amount"))
        return qs.filter(Q(amount_paid__gt=0) & Q(amount_paid__lt=F("total_amount")))


class ExpenseListView(ActionAPIView):
    write_action = RECORD
    serializer_class = ExpenseSerializer
    filterset_class = ExpenseFilter
    ordering_fields = ("expense_date", "total_amount")

    def get_queryset(self) -> Any:
        return Expense.objects.all()

    @extend_schema(responses={200: ExpenseSerializer(many=True)}, tags=["expenses"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), ExpenseSerializer)

    @extend_schema(
        request=ExpenseWriteSerializer, responses={201: ExpenseSerializer}, tags=["expenses"]
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = ExpenseWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        expense = services.record_expense(self.principal, dict(data.validated_data))
        return detail_response(expense, ExpenseSerializer, status=201)


class ExpenseDetailView(ActionAPIView):
    write_action = RECORD

    @extend_schema(responses={200: ExpenseSerializer}, tags=["expenses"])
    def get(self, request: Request, expense_id: uuid.UUID) -> Response:
        expense = services.get_expense(self.principal, expense_id)
        return detail_response(expense, ExpenseSerializer)

    @extend_schema(
        request=ExpenseWriteSerializer, responses={200: ExpenseSerializer}, tags=["expenses"]
    )
    def patch(self, request: Request, expense_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_expense(self.principal, expense_id),
            input_serializer=ExpenseWriteSerializer,
            update=lambda v, changes: services.update_expense(
                self.principal, expense_id, v, changes
            ),
            output_serializer=ExpenseSerializer,
        )


class ExpenseVoidView(ActionAPIView):
    read_action = RECORD
    write_action = RECORD

    @extend_schema(request=None, responses={200: ExpenseSerializer}, tags=["expenses"])
    def post(self, request: Request, expense_id: uuid.UUID) -> Response:
        return versioned_action(
            request,
            load=lambda: services.get_expense(self.principal, expense_id),
            run=lambda v: services.void_expense(self.principal, expense_id, v),
            output_serializer=ExpenseSerializer,
        )
