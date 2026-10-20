"""Project and BOQ endpoints (docs/02-api-design.md §4)."""

import uuid
from typing import Any

import django_filters
from django.db.models import Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.errors import Invalid
from apps.core.idempotency import idempotent

from . import boq_import, services
from .models import BoqItem, Project
from .serializers import (
    BoqImportRequestSerializer,
    BoqImportResultSerializer,
    BoqItemSerializer,
    BoqItemWriteSerializer,
    BoqProgressSerializer,
    ProjectSerializer,
    ProjectWriteSerializer,
)


class ProjectFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="search", label="Name or code")
    client_party_id = django_filters.UUIDFilter(field_name="client_party_id")

    class Meta:
        model = Project
        fields = ("status",)

    def search(self, queryset: QuerySet[Project], name: str, value: str) -> QuerySet[Project]:
        value = value.strip()
        return queryset.filter(Q(name__icontains=value) | Q(code__iexact=value))


class ProjectListView(ActionAPIView):
    write_action = "masters.edit"
    serializer_class = ProjectSerializer
    filterset_class = ProjectFilter
    ordering_fields = ("code", "name", "start_date")

    def get_queryset(self) -> Any:
        return Project.objects.all()

    @extend_schema(responses={200: ProjectSerializer(many=True)}, tags=["projects"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), ProjectSerializer)

    @extend_schema(
        request=ProjectWriteSerializer, responses={201: ProjectSerializer}, tags=["projects"]
    )
    def post(self, request: Request) -> Response:
        data = ProjectWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        project = services.create_project(self.principal, data.validated_data)
        return detail_response(project, ProjectSerializer, status=201)


class ProjectDetailView(ActionAPIView):
    write_action = "masters.edit"

    @extend_schema(responses={200: ProjectSerializer}, tags=["projects"])
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        project = services.get_project(self.principal, project_id)
        return detail_response(project, ProjectSerializer)

    @extend_schema(
        request=ProjectWriteSerializer, responses={200: ProjectSerializer}, tags=["projects"]
    )
    def patch(self, request: Request, project_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_project(self.principal, project_id),
            input_serializer=ProjectWriteSerializer,
            update=lambda v, changes: services.update_project(
                self.principal, project_id, v, changes
            ),
            output_serializer=ProjectSerializer,
        )


class BoqItemListView(ActionAPIView):
    write_action = "boq.edit"
    serializer_class = BoqItemSerializer
    filterset_fields = ("is_variation",)
    ordering_fields = ("sort_order", "item_code")

    def get_queryset(self) -> Any:
        return BoqItem.objects.filter(project_id=self.kwargs.get("project_id"))

    @extend_schema(responses={200: BoqItemSerializer(many=True)}, tags=["projects"])
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        services.get_project(self.principal, project_id)  # 404 for unknown / other tenant
        return list_response(self, self.get_queryset(), BoqItemSerializer)

    @extend_schema(
        request=BoqItemWriteSerializer, responses={201: BoqItemSerializer}, tags=["projects"]
    )
    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        data = BoqItemWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        item = services.create_boq_item(self.principal, project_id, data.validated_data)
        return detail_response(item, BoqItemSerializer, status=201)


class BoqItemDetailView(ActionAPIView):
    write_action = "boq.edit"

    @extend_schema(responses={200: BoqItemSerializer}, tags=["projects"])
    def get(self, request: Request, item_id: uuid.UUID) -> Response:
        return detail_response(services.get_boq_item(self.principal, item_id), BoqItemSerializer)

    @extend_schema(
        request=BoqItemWriteSerializer, responses={200: BoqItemSerializer}, tags=["projects"]
    )
    def patch(self, request: Request, item_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_boq_item(self.principal, item_id),
            input_serializer=BoqItemWriteSerializer,
            update=lambda v, changes: services.update_boq_item(self.principal, item_id, v, changes),
            output_serializer=BoqItemSerializer,
        )

    @extend_schema(responses={204: None}, tags=["projects"])
    def delete(self, request: Request, item_id: uuid.UUID) -> Response:
        services.delete_boq_item(self.principal, item_id)
        return Response(status=204)


class BoqImportView(ActionAPIView):
    """Bulk-add BOQ items from a CSV / XLSX file, all or nothing."""

    write_action = "boq.edit"
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={"multipart/form-data": BoqImportRequestSerializer},
        responses={200: BoqImportResultSerializer, 201: BoqImportResultSerializer},
        tags=["projects"],
    )
    @idempotent
    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        params = BoqImportRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        upload, dry_run = params.validated_data["file"], params.validated_data["dry_run"]
        if upload.size > boq_import.MAX_BYTES:
            raise Invalid("file", "At most 5 MB per import.", code="file_too_large")
        result = services.import_boq_items(
            self.principal, project_id, upload.read(), dry_run=dry_run
        )
        return Response(BoqImportResultSerializer(result).data, status=200 if dry_run else 201)


class BoqProgressView(ActionAPIView):
    """Contract vs billed per BOQ item; all items, not paginated."""

    pagination_class = None

    @extend_schema(responses={200: BoqProgressSerializer}, tags=["projects"])
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        progress = services.boq_progress(self.principal, project_id)
        return Response(BoqProgressSerializer(progress).data)
