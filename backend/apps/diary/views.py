"""Site diary endpoints (Part B; docs/02-api-design.md)."""

import uuid
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent
from apps.core.queries import get_or_404
from apps.documents.models import Document
from apps.projects.models import Project

from . import proof, services
from .models import DiaryEntry
from .serializers import (
    ChoosePhotosSerializer,
    DiaryQuerySerializer,
    EntrySerializer,
    EntryUpdateSerializer,
    EntryWriteSerializer,
    PhotosInSerializer,
    ProofPhotosSerializer,
)


class ProjectDiaryView(ActionAPIView):
    """A project's days, newest first; write a day."""

    write_action = services.WRITE
    serializer_class = EntrySerializer
    ordering_fields = ("entry_date",)
    ordering = ("-entry_date",)  # newest day first (one entry per day and project)

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return DiaryEntry.objects.none()
        return (
            DiaryEntry.objects.filter(project_id=self.kwargs["project_id"])
            .select_related("created_by")
            .order_by("-entry_date")
        )

    @extend_schema(
        parameters=[DiaryQuerySerializer],
        responses={200: EntrySerializer(many=True)},
        tags=["diary"],
    )
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        get_or_404(Project, project_id)
        params = DiaryQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        qs = self.get_queryset()
        if params.validated_data.get("date_from"):
            qs = qs.filter(entry_date__gte=params.validated_data["date_from"])
        if params.validated_data.get("date_to"):
            qs = qs.filter(entry_date__lte=params.validated_data["date_to"])
        return list_response(self, qs, EntrySerializer)

    @extend_schema(request=EntryWriteSerializer, responses={201: EntrySerializer}, tags=["diary"])
    @idempotent
    def post(self, request: Request, project_id: uuid.UUID) -> Response:
        data = EntryWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        entry = services.record(self.principal, project_id, dict(data.validated_data))
        return detail_response(entry, EntrySerializer, status=201)


class DiaryEntryView(ActionAPIView):
    write_action = services.WRITE

    @extend_schema(responses={200: EntrySerializer}, tags=["diary"])
    def get(self, request: Request, entry_id: uuid.UUID) -> Response:
        return detail_response(get_or_404(DiaryEntry, entry_id), EntrySerializer)

    @extend_schema(request=EntryUpdateSerializer, responses={200: EntrySerializer}, tags=["diary"])
    def patch(self, request: Request, entry_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: get_or_404(DiaryEntry, entry_id),
            input_serializer=EntryUpdateSerializer,
            update=lambda v, changes: services.update(self.principal, entry_id, v, changes),
            output_serializer=EntrySerializer,
        )


class DiaryPhotosView(ActionAPIView):
    """Add photos to a day (uploaded first through /attachments)."""

    read_action = services.WRITE
    write_action = services.WRITE

    @extend_schema(request=PhotosInSerializer, responses={200: EntrySerializer}, tags=["diary"])
    def post(self, request: Request, entry_id: uuid.UUID) -> Response:
        data = PhotosInSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        entry = services.add_photos(self.principal, entry_id, data.validated_data["photos"])
        return detail_response(entry, EntrySerializer)


class DiaryPhotoView(ActionAPIView):
    read_action = services.WRITE
    write_action = services.WRITE

    @extend_schema(responses={204: None}, tags=["diary"])
    def delete(self, request: Request, photo_id: uuid.UUID) -> Response:
        services.remove_photo(self.principal, photo_id)
        return Response(status=204)


class DocumentPhotosView(ActionAPIView):
    """A bill's proof-of-work photos; choose them (from its project's diary)."""

    write_action = proof.CHOOSE
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: ProofPhotosSerializer}, tags=["diary"])
    def get(self, request: Request, document_id: uuid.UUID) -> Response:
        doc = get_or_404(Document, document_id)
        return Response(ProofPhotosSerializer({"results": proof.photos(doc)}).data)

    @extend_schema(
        request=ChoosePhotosSerializer, responses={200: ProofPhotosSerializer}, tags=["diary"]
    )
    def put(self, request: Request, document_id: uuid.UUID) -> Response:
        data = ChoosePhotosSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        doc = proof.choose(self.principal, document_id, data.validated_data["diary_photo_ids"])
        return Response(ProofPhotosSerializer({"results": proof.photos(doc)}).data)
