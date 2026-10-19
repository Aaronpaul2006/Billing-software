"""Tenant administration endpoints (docs/02-api-design.md §3)."""

import uuid
from typing import Any

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView
from apps.core.errors import PreconditionFailed
from apps.core.versioning import attach_current, expected_version, with_etag

from . import services
from .models import DocumentSeries, GstRegistration
from .serializers import (
    DocumentSeriesCreateSerializer,
    DocumentSeriesSerializer,
    DocumentSeriesUpdateSerializer,
    GstRegistrationCreateSerializer,
    GstRegistrationSerializer,
    GstRegistrationUpdateSerializer,
    TenantSerializer,
    TenantUpdateSerializer,
)

SETTINGS = "tenant.settings"


def _list(view: ActionAPIView, queryset: Any, serializer: Any) -> Response:
    page = view.paginate_queryset(view.filter_queryset(queryset))
    return view.get_paginated_response(serializer(page, many=True).data)


# --- business profile ---------------------------------------------------------------


class TenantView(ActionAPIView):
    write_action = SETTINGS

    @extend_schema(responses={200: TenantSerializer}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        tenant = services.get_tenant(self.principal)
        return with_etag(Response(TenantSerializer(tenant).data), tenant.version)

    @extend_schema(
        request=TenantUpdateSerializer, responses={200: TenantSerializer}, tags=["tenant"]
    )
    def patch(self, request: Request) -> Response:
        expected = expected_version(request)
        data = TenantUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        try:
            tenant = services.update_tenant(self.principal, expected, data.validated_data)
        except PreconditionFailed as exc:
            attach_current(exc, lambda: TenantSerializer(services.get_tenant(self.principal)).data)
            raise
        return with_etag(Response(TenantSerializer(tenant).data), tenant.version)


# --- GST registrations ---------------------------------------------------------------


class GstRegistrationListView(ActionAPIView):
    write_action = SETTINGS
    serializer_class = GstRegistrationSerializer
    filterset_fields = ("registration_type", "is_active", "state_code")

    def get_queryset(self) -> Any:
        return GstRegistration.objects.all()

    @extend_schema(responses={200: GstRegistrationSerializer(many=True)}, tags=["tenant"])
    def get(self, request: Request) -> Response:
        return _list(self, self.get_queryset(), GstRegistrationSerializer)

    @extend_schema(
        request=GstRegistrationCreateSerializer,
        responses={201: GstRegistrationSerializer},
        tags=["tenant"],
    )
    def post(self, request: Request) -> Response:
        data = GstRegistrationCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        registration = services.create_registration(self.principal, data.validated_data)
        body = GstRegistrationSerializer(registration).data
        return with_etag(Response(body, status=201), registration.version)


class GstRegistrationDetailView(ActionAPIView):
    write_action = SETTINGS

    @extend_schema(responses={200: GstRegistrationSerializer}, tags=["tenant"])
    def get(self, request: Request, registration_id: uuid.UUID) -> Response:
        registration = services.get_registration(self.principal, registration_id)
        body = GstRegistrationSerializer(registration).data
        return with_etag(Response(body), registration.version)

    @extend_schema(
        request=GstRegistrationUpdateSerializer,
        responses={200: GstRegistrationSerializer},
        tags=["tenant"],
    )
    def patch(self, request: Request, registration_id: uuid.UUID) -> Response:
        registration = services.get_registration(self.principal, registration_id)
        expected = expected_version(request)
        data = GstRegistrationUpdateSerializer(
            data=request.data, partial=True, context={"registration": registration}
        )
        data.is_valid(raise_exception=True)
        try:
            registration = services.update_registration(
                self.principal, registration_id, expected, data.validated_data
            )
        except PreconditionFailed as exc:
            attach_current(
                exc,
                lambda: (
                    GstRegistrationSerializer(
                        services.get_registration(self.principal, registration_id)
                    ).data
                ),
            )
            raise
        body = GstRegistrationSerializer(registration).data
        return with_etag(Response(body), registration.version)


# --- number series -------------------------------------------------------------------


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
        return _list(self, self.get_queryset(), DocumentSeriesSerializer)

    @extend_schema(
        request=DocumentSeriesCreateSerializer,
        responses={201: DocumentSeriesSerializer},
        tags=["tenant"],
    )
    def post(self, request: Request) -> Response:
        data = DocumentSeriesCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        series = services.create_series(self.principal, data.validated_data)
        return with_etag(
            Response(DocumentSeriesSerializer(series).data, status=201), series.version
        )


class DocumentSeriesDetailView(ActionAPIView):
    write_action = SETTINGS

    @extend_schema(responses={200: DocumentSeriesSerializer}, tags=["tenant"])
    def get(self, request: Request, series_id: uuid.UUID) -> Response:
        series = services.get_series(self.principal, series_id)
        return with_etag(Response(DocumentSeriesSerializer(series).data), series.version)

    @extend_schema(
        request=DocumentSeriesUpdateSerializer,
        responses={200: DocumentSeriesSerializer},
        tags=["tenant"],
    )
    def patch(self, request: Request, series_id: uuid.UUID) -> Response:
        services.get_series(self.principal, series_id)  # 404 before 428/412
        expected = expected_version(request)
        data = DocumentSeriesUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        try:
            series = services.update_series(
                self.principal, series_id, expected, data.validated_data
            )
        except PreconditionFailed as exc:
            attach_current(
                exc,
                lambda: (
                    DocumentSeriesSerializer(services.get_series(self.principal, series_id)).data
                ),
            )
            raise
        return with_etag(Response(DocumentSeriesSerializer(series).data), series.version)
