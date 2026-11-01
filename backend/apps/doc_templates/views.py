"""Quotation / bill templates (W.3, docs/02-api-design.md §5)."""

import uuid
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent, idempotent_if_keyed
from apps.documents.serializers import DocumentSerializer

from . import services
from .models import DocumentTemplate
from .serializers import (
    SaveAsTemplateSerializer,
    TemplateSerializer,
    TemplateWriteSerializer,
    UseTemplateSerializer,
)


class TemplateListView(ActionAPIView):
    write_action = services.EDIT
    serializer_class = TemplateSerializer
    filterset_fields = ("doc_type",)
    ordering_fields = ("name", "created_at")

    def get_queryset(self) -> Any:
        return DocumentTemplate.objects.all()

    @extend_schema(responses={200: TemplateSerializer(many=True)}, tags=["templates"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), TemplateSerializer)

    @extend_schema(
        request=TemplateWriteSerializer, responses={201: TemplateSerializer}, tags=["templates"]
    )
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        data = TemplateWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        template = services.create_template(self.principal, dict(data.validated_data))
        return detail_response(template, TemplateSerializer, status=201)


class TemplateDetailView(ActionAPIView):
    write_action = services.EDIT

    @extend_schema(responses={200: TemplateSerializer}, tags=["templates"])
    def get(self, request: Request, template_id: uuid.UUID) -> Response:
        return detail_response(
            services.get_template(self.principal, template_id), TemplateSerializer
        )

    @extend_schema(
        request=TemplateWriteSerializer, responses={200: TemplateSerializer}, tags=["templates"]
    )
    def patch(self, request: Request, template_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_template(self.principal, template_id),
            input_serializer=TemplateWriteSerializer,
            update=lambda v, changes: services.update_template(
                self.principal, template_id, v, changes
            ),
            output_serializer=TemplateSerializer,
        )

    @extend_schema(responses={204: None}, tags=["templates"])
    def delete(self, request: Request, template_id: uuid.UUID) -> Response:
        services.delete_template(self.principal, template_id)
        return Response(status=204)


class TemplateUseView(ActionAPIView):
    write_action = "documents.draft"

    @extend_schema(
        request=UseTemplateSerializer, responses={201: DocumentSerializer}, tags=["templates"]
    )
    @idempotent
    def post(self, request: Request, template_id: uuid.UUID) -> Response:
        data = UseTemplateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        doc = services.use_template(self.principal, template_id, dict(data.validated_data))
        return detail_response(doc, DocumentSerializer, status=201)


class SaveAsTemplateView(ActionAPIView):
    write_action = services.EDIT

    @extend_schema(
        request=SaveAsTemplateSerializer, responses={201: TemplateSerializer}, tags=["templates"]
    )
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        data = SaveAsTemplateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        template = services.save_document_as_template(
            self.principal,
            document_id,
            data.validated_data["name"],
            data.validated_data.get("valid_days"),
        )
        return detail_response(template, TemplateSerializer, status=201)
