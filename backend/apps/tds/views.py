"""TDS certificate endpoints (docs/02-api-design.md §6)."""

import uuid
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent

from . import services
from .models import TdsCertificate
from .serializers import TdsCertificateSerializer, TdsCertificateWriteSerializer


class TdsCertificateListView(ActionAPIView):
    write_action = services.RECORD
    serializer_class = TdsCertificateSerializer
    filterset_fields = ("party_id", "fy_start_year", "quarter", "deductor_tan")
    ordering_fields = ("fy_start_year", "quarter", "certificate_date")

    def get_queryset(self) -> Any:
        return TdsCertificate.objects.select_related("party")  # names, one query

    @extend_schema(responses={200: TdsCertificateSerializer(many=True)}, tags=["tds"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), TdsCertificateSerializer)

    @extend_schema(
        request=TdsCertificateWriteSerializer,
        responses={201: TdsCertificateSerializer},
        tags=["tds"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = TdsCertificateWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = services.create_certificate(self.principal, dict(data.validated_data))
        return detail_response(row, TdsCertificateSerializer, status=201)


class TdsCertificateDetailView(ActionAPIView):
    write_action = services.RECORD

    @extend_schema(responses={200: TdsCertificateSerializer}, tags=["tds"])
    def get(self, request: Request, certificate_id: uuid.UUID) -> Response:
        row = services.get_certificate(self.principal, certificate_id)
        return detail_response(row, TdsCertificateSerializer)

    @extend_schema(
        request=TdsCertificateWriteSerializer,
        responses={200: TdsCertificateSerializer},
        tags=["tds"],
    )
    def patch(self, request: Request, certificate_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_certificate(self.principal, certificate_id),
            input_serializer=TdsCertificateWriteSerializer,
            update=lambda v, changes: services.update_certificate(
                self.principal, certificate_id, v, changes
            ),
            output_serializer=TdsCertificateSerializer,
        )

    @extend_schema(responses={204: None}, tags=["tds"])
    def delete(self, request: Request, certificate_id: uuid.UUID) -> Response:
        services.delete_certificate(self.principal, certificate_id)
        return Response(status=204)
