"""Catalog endpoints (docs/02-api-design.md §4)."""

import uuid
from typing import Any

import django_filters
from django.db.models import Max, OuterRef, Prefetch, Q, QuerySet, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent_if_keyed
from apps.documents.models import DocumentLine

from . import services
from .models import CatalogItem, CatalogItemVariant
from .serializers import (
    CatalogItemSerializer,
    CatalogItemWriteSerializer,
    CatalogVariantListSerializer,
    CatalogVariantSerializer,
    CatalogVariantWriteSerializer,
)

EDIT = "masters.edit"


class CatalogItemFilter(django_filters.FilterSet):
    is_active = django_filters.BooleanFilter()
    sac_hsn = django_filters.CharFilter()
    q = django_filters.CharFilter(
        method="search", label="Words of the name or description, a variant, or the HSN/SAC start"
    )

    used = django_filters.BooleanFilter(
        method="filter_used", label="true: only items already used on a bill"
    )

    class Meta:
        model = CatalogItem
        fields: tuple[str, ...] = ()

    def filter_used(
        self, qs: QuerySet[CatalogItem], name: str, value: bool
    ) -> QuerySet[CatalogItem]:
        return qs.filter(**{"last_used_at__isnull": not value})  # an annotation (get_queryset)

    def search(self, qs: QuerySet[CatalogItem], name: str, value: str) -> QuerySet[CatalogItem]:
        match = Q()
        for word in value.split()[:5]:  # every word must match somewhere
            variant = CatalogItemVariant.objects.filter(
                catalog_item_id=OuterRef("pk"), value__icontains=word
            )
            match &= (
                Q(name__icontains=word)
                | Q(description__icontains=word)
                | Q(sac_hsn__startswith=word)
                | Q(pk__in=variant.values("catalog_item_id"))
            )
        return qs.filter(match)


class CatalogItemListView(ActionAPIView):
    """Recent items for the bill screen: `used=true&ordering=-last_used_at`."""

    write_action = EDIT
    serializer_class = CatalogItemSerializer
    filterset_class = CatalogItemFilter
    ordering_fields = ("name", "last_used_at")

    def get_queryset(self) -> Any:
        last_used = (
            DocumentLine.objects.filter(catalog_item_id=OuterRef("pk"))
            .values("catalog_item_id")
            .annotate(at=Max("document__created_at"))
            .values("at")
        )
        return CatalogItem.objects.annotate(last_used_at=Subquery(last_used)).prefetch_related(
            Prefetch(
                "variants",
                queryset=CatalogItemVariant.objects.order_by("attribute", "value"),
                to_attr="prefetched_variants",
            )
        )

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


class CatalogVariantListView(ActionAPIView):
    write_action = EDIT
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: CatalogVariantListSerializer}, tags=["catalog"])
    def get(self, request: Request, item_id: uuid.UUID) -> Response:
        rows = services.list_variants(self.principal, item_id)
        return Response({"results": CatalogVariantSerializer(rows, many=True).data})

    @extend_schema(
        request=CatalogVariantWriteSerializer,
        responses={201: CatalogVariantSerializer},
        tags=["catalog"],
    )
    @idempotent_if_keyed
    def post(self, request: Request, item_id: uuid.UUID) -> Response:
        data = CatalogVariantWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        variant = services.create_variant(self.principal, item_id, dict(data.validated_data))
        return detail_response(variant, CatalogVariantSerializer, status=201)


class CatalogVariantDetailView(ActionAPIView):
    write_action = EDIT

    @extend_schema(responses={200: CatalogVariantSerializer}, tags=["catalog"])
    def get(self, request: Request, variant_id: uuid.UUID) -> Response:
        return detail_response(
            services.get_variant(self.principal, variant_id), CatalogVariantSerializer
        )

    @extend_schema(
        request=CatalogVariantWriteSerializer,
        responses={200: CatalogVariantSerializer},
        tags=["catalog"],
    )
    def patch(self, request: Request, variant_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_variant(self.principal, variant_id),
            input_serializer=CatalogVariantWriteSerializer,
            update=lambda v, changes: services.update_variant(
                self.principal, variant_id, v, changes
            ),
            output_serializer=CatalogVariantSerializer,
        )

    @extend_schema(responses={204: None}, tags=["catalog"])
    def delete(self, request: Request, variant_id: uuid.UUID) -> Response:
        services.delete_variant(self.principal, variant_id)
        return Response(status=204)
