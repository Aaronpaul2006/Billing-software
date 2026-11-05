"""Search across the business for the Ctrl+K command palette (D.6).

Read-only, `tenant.read`: every member, the same data the lists show. A few
matches of each kind; everything stays in the caller's tenant (RLS and the
tenant-scoped managers). `icontains` escapes % and _, so they match themselves.
"""

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.catalog.models import CatalogItem
from apps.core.api import ActionAPIView
from apps.documents.models import Document
from apps.parties.models import Party
from apps.projects.models import Project

from .serializers import (
    SearchCatalogItemSerializer,
    SearchDocumentSerializer,
    SearchParamsSerializer,
    SearchPartySerializer,
    SearchProjectSerializer,
    SearchResultSerializer,
)

LIMIT = 5  # of each kind


class SearchView(ActionAPIView):
    read_action = "tenant.read"
    pagination_class = None
    filter_backends = ()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "q",
                str,
                required=True,
                description="2 to 100 characters: a bill number, a name, a project code, an HSN",
            )
        ],
        responses={200: SearchResultSerializer},
        tags=["search"],
    )
    def get(self, request: Request) -> Response:
        params = SearchParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        q: str = params.validated_data["q"]
        documents = (
            Document.objects.select_related("party")
            .filter(
                Q(doc_number__icontains=q)
                | Q(party__display_name__icontains=q)
                | Q(party_snapshot__display_name__icontains=q)
            )
            .order_by("-doc_date", "-created_at")[:LIMIT]
        )
        parties = Party.objects.filter(
            Q(display_name__icontains=q) | Q(legal_name__icontains=q) | Q(gstin=q.upper())
        ).order_by("-is_active", "display_name")[:LIMIT]
        projects = (
            Project.objects.select_related("client_party")
            .filter(Q(name__icontains=q) | Q(code__icontains=q))
            .order_by("name")[:LIMIT]
        )
        items = CatalogItem.objects.filter(
            Q(name__icontains=q) | Q(sac_hsn__startswith=q), is_active=True
        ).order_by("name")[:LIMIT]
        return Response(
            {
                "documents": SearchDocumentSerializer(documents, many=True).data,
                "parties": SearchPartySerializer(parties, many=True).data,
                "projects": SearchProjectSerializer(projects, many=True).data,
                "catalog_items": SearchCatalogItemSerializer(items, many=True).data,
            }
        )
