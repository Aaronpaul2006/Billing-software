"""Client-portal endpoints (W.5b, docs/02-api-design.md §10): role CLIENT only.

Staff tokens get 403 here, and client tokens get 403 on every staff endpoint
(tests/accounts/test_client_portal.py)."""

import uuid
from typing import Any

import django_filters
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import detail_response, list_response, principal_of, versioned_action
from apps.core.permissions import IsClient, MfaSatisfied
from apps.core.tenancy import Principal
from apps.documents.models import Document
from apps.documents.serializers import PdfLinkSerializer
from apps.documents.services import pdfs
from apps.files import storage
from apps.files.models import Attachment
from apps.projects.serializers import BoqProgressSerializer
from apps.reports.serializers import PeriodSerializer, StatementSerializer
from apps.reports.views import PERIOD_PARAMS

from . import services
from .serializers import (
    PortalDocumentDetailSerializer,
    PortalDocumentSerializer,
    PortalMeSerializer,
    PortalPaymentSerializer,
    PortalProjectListSerializer,
    PortalProjectSerializer,
)


class PortalView(GenericAPIView):  # type: ignore[type-arg]
    permission_classes = (IsAuthenticated, MfaSatisfied, IsClient)

    @property
    def principal(self) -> Principal:
        return principal_of(self.request)


class MeView(PortalView):
    pagination_class = None

    @extend_schema(responses={200: PortalMeSerializer}, tags=["portal"])
    def get(self, request: Request) -> Response:
        return Response(PortalMeSerializer(services.me(self.principal)).data)


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class PortalDocumentFilter(django_filters.FilterSet):
    doc_type = CharInFilter(field_name="doc_type", lookup_expr="in")
    status = CharInFilter(field_name="status", lookup_expr="in")
    project_id = django_filters.UUIDFilter(field_name="project_id")

    class Meta:
        model = Document
        fields: tuple[str, ...] = ()


class DocumentListView(PortalView):
    """The client's bills, RA bills, notes and quotations (never drafts), newest first."""

    serializer_class = PortalDocumentSerializer
    filterset_class = PortalDocumentFilter
    ordering_fields = ("doc_date", "doc_number")

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):  # schema generation: no caller
            return Document.objects.none()
        return services.documents(self.principal)

    @extend_schema(responses={200: PortalDocumentSerializer(many=True)}, tags=["portal"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), PortalDocumentSerializer)


class DocumentDetailView(PortalView):
    @extend_schema(responses={200: PortalDocumentDetailSerializer}, tags=["portal"])
    def get(self, request: Request, document_id: uuid.UUID) -> Response:
        doc = services.document(self.principal, document_id)
        return detail_response(doc, PortalDocumentDetailSerializer)


class DocumentPdfView(PortalView):
    """302 to a short-lived link to the issued PDF (202 while it is being made)."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "as",
                str,
                enum=["link"],
                description="`link`: answer 200 {url, expires_in} instead of a 302 (browsers).",
            )
        ],
        responses={
            (200, "application/json"): PdfLinkSerializer,
            302: None,
            202: {"type": "object", "properties": {"status": {"type": "string"}}},
        },
        tags=["portal"],
    )
    def get(self, request: Request, document_id: uuid.UUID) -> HttpResponseBase:
        doc = services.document(self.principal, document_id)
        attachment = (
            Attachment.objects.filter(pk=doc.pdf_attachment_id, status="AVAILABLE").first()
            if doc.pdf_attachment_id
            else None
        )
        if attachment is None:
            pdfs.enqueue_pdf(self.principal.tenant_id, self.principal.user_id, doc.pk)
            return Response({"status": "rendering"}, status=202, headers={"Retry-After": "3"})
        url = storage.download_url(attachment.storage_key, attachment.original_filename)
        if request.query_params.get("as") == "link":
            return Response({"url": url, "expires_in": storage.DOWNLOAD_URL_TTL})
        return HttpResponseRedirect(url)


class QuotationResponseView(PortalView):
    """Accept or decline a quotation (needs If-Match; 409 once expired or answered)."""

    accept = True

    @extend_schema(request=None, responses={200: PortalDocumentDetailSerializer}, tags=["portal"])
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        return versioned_action(
            request,
            load=lambda: services.document(self.principal, document_id),
            run=lambda v: services.respond_to_quotation(
                self.principal, document_id, v, accept=self.accept
            ),
            output_serializer=PortalDocumentDetailSerializer,
        )


class QuotationDeclineView(QuotationResponseView):
    accept = False


class PaymentListView(PortalView):
    """Payments received from the client (voided ones are not shown), newest first."""

    serializer_class = PortalPaymentSerializer
    filter_backends = ()

    def get_queryset(self) -> Any:
        return services.payments(self.principal)

    @extend_schema(responses={200: PortalPaymentSerializer(many=True)}, tags=["portal"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), PortalPaymentSerializer)


class StatementView(PortalView):
    """The client's statement of account between `from` and `to` (default: this FY to today)."""

    pagination_class = None
    filter_backends = ()

    @extend_schema(
        parameters=PERIOD_PARAMS[:2], responses={200: StatementSerializer}, tags=["portal"]
    )
    def get(self, request: Request) -> Response:
        params = PeriodSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        p = params.validated_data
        return Response(
            StatementSerializer(services.statement(self.principal, p["start"], p["end"])).data
        )


class ProjectListView(PortalView):
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: PortalProjectListSerializer}, tags=["portal"])
    def get(self, request: Request) -> Response:
        rows = services.projects(self.principal)
        return Response({"results": PortalProjectSerializer(rows, many=True).data})


class BoqProgressView(PortalView):
    """Contract vs billed per BOQ item of one of the client's projects."""

    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: BoqProgressSerializer}, tags=["portal"])
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        return Response(
            BoqProgressSerializer(services.boq_progress(self.principal, project_id)).data
        )
