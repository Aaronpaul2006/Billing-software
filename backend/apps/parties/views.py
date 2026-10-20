"""Party endpoints (docs/02-api-design.md §4)."""

import uuid
from typing import Any

import django_filters
from django.db.models import Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, detail_response, list_response, versioned_patch
from apps.core.idempotency import idempotent_if_keyed

from . import services
from .models import Party
from .serializers import PartySerializer, PartyWriteSerializer

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
