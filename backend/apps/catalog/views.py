"""Catalog endpoints (docs/02-api-design.md §4)."""

import uuid
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent_if_keyed

from . import services
from .models import CatalogItem
from .serializers import CatalogItemSerializer, CatalogItemWriteSerializer

EDIT = "masters.edit"


class CatalogItemListView(ActionAPIView):
    write_action = EDIT
    serializer_class = CatalogItemSerializer
    filterset_fields = ("is_active", "sac_hsn")
    ordering_fields = ("name",)

    def get_queryset(self) -> Any:
        return CatalogItem.objects.all()

    @extend_schema(responses={200: CatalogItemSerializer(many=True)}, tags=["catalog"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), CatalogItemSerializer)

    @extend_schema(
        request=CatalogItemWriteSerializer, responses={201: CatalogItemSerializer}, tags=["catalog"]
    )
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        data = CatalogItemWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        item = services.create_item(self.principal, data.validated_data)
        return detail_response(item, CatalogItemSerializer, status=201)


class CatalogItemDetailView(ActionAPIView):
    write_action = EDIT

    @extend_schema(responses={200: CatalogItemSerializer}, tags=["catalog"])
    def get(self, request: Request, item_id: uuid.UUID) -> Response:
        return detail_response(services.get_item(self.principal, item_id), CatalogItemSerializer)

    @extend_schema(
        request=CatalogItemWriteSerializer, responses={200: CatalogItemSerializer}, tags=["catalog"]
    )
    def patch(self, request: Request, item_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_item(self.principal, item_id),
            input_serializer=CatalogItemWriteSerializer,
            update=lambda v, changes: services.update_item(self.principal, item_id, v, changes),
            output_serializer=CatalogItemSerializer,
        )

    @extend_schema(responses={204: None}, tags=["catalog"])
    def delete(self, request: Request, item_id: uuid.UUID) -> Response:
        services.delete_item(self.principal, item_id)
        return Response(status=204)
