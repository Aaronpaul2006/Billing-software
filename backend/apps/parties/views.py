"""Party endpoints (docs/02-api-design.md §4)."""

import uuid
from typing import Any

import django_filters
from django.db.models import Q, QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.errors import Invalid
from apps.core.idempotency import idempotent, idempotent_if_keyed
from apps.core.imports import (
    ImportRequestSerializer,
    SampleQuerySerializer,
    sample_response,
    upload_bytes,
)

from . import importer, services, tally, tally_import
from .models import Party
from .serializers import (
    KINDS,
    PartyImportResultSerializer,
    PartySerializer,
    PartyWriteSerializer,
    TallyImportRequestSerializer,
    TallyImportResultSerializer,
)

EDIT = "masters.edit"


class PartyFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="search", label="Name or GSTIN")

    class Meta:
        model = Party
        fields = ("is_customer", "is_vendor", "is_active", "gst_treatment", "state_code")

    def search(self, queryset: QuerySet[Party], name: str, value: str) -> QuerySet[Party]:
        value = value.strip()
        # display_name ILIKE uses the trigram index (parties_name_trgm_idx)
        return queryset.filter(Q(display_name__icontains=value) | Q(gstin=value.upper()))


class PartyListView(ActionAPIView):
    write_action = EDIT
    serializer_class = PartySerializer
    filterset_class = PartyFilter
    ordering_fields = ("display_name", "created_at")

    def get_queryset(self) -> Any:
        return Party.objects.all()

    @extend_schema(responses={200: PartySerializer(many=True)}, tags=["parties"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), PartySerializer)

    @extend_schema(request=PartyWriteSerializer, responses={201: PartySerializer}, tags=["parties"])
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        data = PartyWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        party = services.create_party(self.principal, data.validated_data)
        return detail_response(party, PartySerializer, status=201)


class PartyImportView(ActionAPIView):
    """Add clients from a CSV / XLSX file, all or nothing (B.3)."""

    write_action = EDIT
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={"multipart/form-data": ImportRequestSerializer},
        responses={200: PartyImportResultSerializer, 201: PartyImportResultSerializer},
        tags=["parties"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        params = ImportRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        dry_run = params.validated_data["dry_run"]
        result = importer.import_parties(
            self.principal, upload_bytes(params.validated_data["file"]), dry_run=dry_run
        )
        return Response(PartyImportResultSerializer(result).data, status=200 if dry_run else 201)


class PartyImportSampleView(ActionAPIView):
    """A sample file to fill in: the columns the client import reads."""

    read_action = EDIT

    @extend_schema(
        parameters=[SampleQuerySerializer],
        responses={(200, "application/octet-stream"): bytes},
        tags=["parties"],
    )
    def get(self, request: Request) -> HttpResponse:
        q = SampleQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        return sample_response(importer.LAYOUT, q.validated_data["type"], "clients-sample")


class PartyDetailView(ActionAPIView):
    write_action = EDIT

    @extend_schema(responses={200: PartySerializer}, tags=["parties"])
    def get(self, request: Request, party_id: uuid.UUID) -> Response:
        return detail_response(services.get_party(self.principal, party_id), PartySerializer)

    @extend_schema(request=PartyWriteSerializer, responses={200: PartySerializer}, tags=["parties"])
    def patch(self, request: Request, party_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: services.get_party(self.principal, party_id),
            input_serializer=PartyWriteSerializer,
            update=lambda v, changes: services.update_party(self.principal, party_id, v, changes),
            output_serializer=PartySerializer,
        )


class TallyImportView(ActionAPIView):
    """Clients, vendors and items from Tally's masters XML (Part B, tally_import.py)."""

    write_action = EDIT
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={"multipart/form-data": TallyImportRequestSerializer},
        responses={200: TallyImportResultSerializer, 201: TallyImportResultSerializer},
        tags=["parties"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        params = TallyImportRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        upload = params.validated_data["file"]
        if upload.size > tally.MAX_BYTES:
            raise Invalid("file", "At most 20 MB per import.", code="file_too_large")
        data = bytes(upload.read())
        dry_run = params.validated_data["dry_run"]
        kinds = params.validated_data.get("kinds") or list(KINDS)
        result = (
            tally_import.plan(self.principal, data)
            if dry_run
            else tally_import.run(self.principal, data, kinds)
        )
        order = {"PROBLEM": 0, "NEW": 1, "EXISTS": 2}
        rows = sorted(result.rows, key=lambda r: (order[r.status], r.kind, r.name.lower()))
        body = {
            "dry_run": dry_run,
            "clients": result.count("CLIENT"),
            "vendors": result.count("VENDOR"),
            "items": result.count("ITEM"),
            "other_ledgers": result.other_ledgers,
            "rows": rows[: tally_import.MAX_ROWS],
            "added": result.added or None,
        }
        return Response(TallyImportResultSerializer(body).data, status=200 if dry_run else 201)
