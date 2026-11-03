"""Tenant administration endpoints (docs/02-api-design.md §3)."""

import uuid
from typing import Any

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent_if_keyed

from . import printing, services
from .models import DocumentSeries, GstRegistration
from .serializers import (
    DocumentSeriesCreateSerializer,
    DocumentSeriesSerializer,
    DocumentSeriesUpdateSerializer,
    GstRegistrationCreateSerializer,
    GstRegistrationSerializer,
    GstRegistrationUpdateSerializer,
    PrintSettingsSerializer,
    PrintSettingsUpdateSerializer,
    SetupStatusSerializer,
    TenantSerializer,
    TenantUpdateSerializer,
)
from .setup import setup_status

SETTINGS = "tenant.settings"


class TenantView(ActionAPIView):
    write_action = SETTINGS

    @extend_schema(responses={200: TenantSerializer}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        return detail_response(services.get_tenant(self.principal), TenantSerializer)

    @extend_schema(
        request=TenantUpdateSerializer, responses={200: TenantSerializer}, tags=["tenant"]
    )
    def patch(self, request: Request) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_tenant(self.principal),
            input_serializer=TenantUpdateSerializer,
            update=lambda v, changes: services.update_tenant(self.principal, v, changes),
            output_serializer=TenantSerializer,
        )


class PrintSettingsView(ActionAPIView):
    """Logo, signature, bank details, UPI ID, default terms and layout of the
    business's bills (B.12). Every member may read them; owners and admins change them."""

    write_action = SETTINGS

    @extend_schema(responses={200: PrintSettingsSerializer}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        return detail_response(printing.get_print_settings(self.principal), PrintSettingsSerializer)

    @extend_schema(
        request=PrintSettingsUpdateSerializer,
        responses={200: PrintSettingsSerializer},
        tags=["tenant"],
    )
    def patch(self, request: Request) -> Response:
        return versioned_patch(
            request,
            load=lambda: printing.get_print_settings(self.principal),
            input_serializer=PrintSettingsUpdateSerializer,
            update=lambda v, changes: printing.update_print_settings(self.principal, v, changes),
            output_serializer=PrintSettingsSerializer,
        )


class SetupStatusView(ActionAPIView):
    """The setup checklist on the first page after sign-in (any member may read it)."""

    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: SetupStatusSerializer}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        return Response(SetupStatusSerializer(setup_status(self.principal.tenant_id)).data)


class GstRegistrationListView(ActionAPIView):
    write_action = SETTINGS
    serializer_class = GstRegistrationSerializer
    filterset_fields = ("registration_type", "is_active", "state_code")

    def get_queryset(self) -> Any:
        return GstRegistration.objects.all()

    @extend_schema(responses={200: GstRegistrationSerializer(many=True)}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), GstRegistrationSerializer)

    @extend_schema(
        request=GstRegistrationCreateSerializer,
        responses={201: GstRegistrationSerializer},
        tags=["tenant"],
    )
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        data = GstRegistrationCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        registration = services.create_registration(self.principal, data.validated_data)
        return detail_response(registration, GstRegistrationSerializer, status=201)


class GstRegistrationDetailView(ActionAPIView):
    write_action = SETTINGS

    @extend_schema(responses={200: GstRegistrationSerializer}, tags=["tenant"])
    def get(self, request: Request, registration_id: uuid.UUID) -> Response:
        registration = services.get_registration(self.principal, registration_id)
        return detail_response(registration, GstRegistrationSerializer)

    @extend_schema(
        request=GstRegistrationUpdateSerializer,
        responses={200: GstRegistrationSerializer},
        tags=["tenant"],
    )
    def patch(self, request: Request, registration_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_registration(self.principal, registration_id),
            input_serializer=GstRegistrationUpdateSerializer,
            update=lambda v, changes: services.update_registration(
                self.principal, registration_id, v, changes
            ),
            output_serializer=GstRegistrationSerializer,
        )


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """?doc_type=TAX_INVOICE,DEBIT_NOTE"""


class DocumentSeriesFilter(django_filters.FilterSet):
    doc_type = CharInFilter(field_name="doc_type", lookup_expr="in")
    gst_registration_id = django_filters.UUIDFilter(field_name="gst_registration_id")

    class Meta:
        model = DocumentSeries
        fields = ("fy_start_year", "is_active")


class DocumentSeriesListView(ActionAPIView):
    write_action = SETTINGS
    serializer_class = DocumentSeriesSerializer
    filterset_class = DocumentSeriesFilter

    def get_queryset(self) -> Any:
        return DocumentSeries.objects.all()

    @extend_schema(responses={200: DocumentSeriesSerializer(many=True)}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), DocumentSeriesSerializer)

    @extend_schema(
        request=DocumentSeriesCreateSerializer,
        responses={201: DocumentSeriesSerializer},
        tags=["tenant"],
    )
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        data = DocumentSeriesCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        series = services.create_series(self.principal, data.validated_data)
        return detail_response(series, DocumentSeriesSerializer, status=201)


class DocumentSeriesDetailView(ActionAPIView):
    write_action = SETTINGS

    @extend_schema(responses={200: DocumentSeriesSerializer}, tags=["tenant"])
    def get(self, request: Request, series_id: uuid.UUID) -> Response:
        series = services.get_series(self.principal, series_id)
        return detail_response(series, DocumentSeriesSerializer)

    @extend_schema(
        request=DocumentSeriesUpdateSerializer,
        responses={200: DocumentSeriesSerializer},
        tags=["tenant"],
    )
    def patch(self, request: Request, series_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_series(self.principal, series_id),
            input_serializer=DocumentSeriesUpdateSerializer,
            update=lambda v, changes: services.update_series(self.principal, series_id, v, changes),
            output_serializer=DocumentSeriesSerializer,
        )
