"""Catalog endpoints (docs/02-api-design.md §4)."""

import uuid
from typing import Any

import django_filters
from django.db.models import Max, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent, idempotent_if_keyed
from apps.core.imports import (
    ImportRequestSerializer,
    SampleQuerySerializer,
    sample_response,
    upload_bytes,
)
from apps.documents.models import DocumentLine

from . import importer, services
from .models import CatalogItem, CatalogItemVariant
from .serializers import (
    CatalogImportResultSerializer,
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


class CatalogImportView(ActionAPIView):
    """Add catalog items from a CSV / XLSX file, all or nothing (B.2)."""

    write_action = EDIT
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={"multipart/form-data": ImportRequestSerializer},
        responses={200: CatalogImportResultSerializer, 201: CatalogImportResultSerializer},
        tags=["catalog"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        params = ImportRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        dry_run = params.validated_data["dry_run"]
        result = importer.import_items(
            self.principal, upload_bytes(params.validated_data["file"]), dry_run=dry_run
        )
        return Response(CatalogImportResultSerializer(result).data, status=200 if dry_run else 201)


class CatalogImportSampleView(ActionAPIView):
    """A sample file to fill in: the columns the item import reads, three example rows."""

    read_action = EDIT

    @extend_schema(
        parameters=[SampleQuerySerializer],
        responses={(200, "application/octet-stream"): bytes},
        tags=["catalog"],
    )
    def get(self, request: Request) -> HttpResponse:
        q = SampleQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        return sample_response(importer.LAYOUT, q.validated_data["type"], "items-sample")


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
