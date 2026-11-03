"""Billing document endpoints (docs/02-api-design.md §5). Drafts in Phase 1.5."""

import uuid
from typing import Any

import django_filters
from django.db.models import F, Q, QuerySet
from django.http import HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import (
    ActionAPIView,
    detail_response,
    list_response,
    versioned_action,
    versioned_patch,
)
from apps.core.errors import Invalid
from apps.core.idempotency import idempotent
from apps.core.imports import SampleQuerySerializer, sample_response, upload_bytes
from apps.files import storage
from apps.files.models import Attachment

from .models import Document
from .pdf.render import render_pdf
from .serializers import (
    CancelSerializer,
    ConvertSerializer,
    DocumentListSerializer,
    DocumentSerializer,
    DocumentWriteSerializer,
    DuplicateSerializer,
    LastRateSerializer,
    LastRatesSerializer,
    NoteSerializer,
    ParseLinesRequestSerializer,
    ParseLinesResultSerializer,
    PdfLinkSerializer,
    PreviewSerializer,
    TotalsSerializer,
)
from .services import drafts, lifecycle, line_import, pdfs, rates

DRAFT = "documents.draft"


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Comma-separated values: ?doc_type=TAX_INVOICE,DEBIT_NOTE"""


class DocumentFilter(django_filters.FilterSet):
    doc_type = CharInFilter(field_name="doc_type", lookup_expr="in")
    status = CharInFilter(field_name="status", lookup_expr="in")
    book = django_filters.ChoiceFilter(
        choices=[("GST", "GST"), ("NON_GST", "NON_GST"), ("ALL", "ALL")], method="filter_book"
    )
    party_id = django_filters.UUIDFilter(field_name="party_id")
    project_id = django_filters.UUIDFilter(field_name="project_id")
    is_ra_bill = django_filters.BooleanFilter(field_name="is_ra_bill")
    doc_date_from = django_filters.DateFilter(field_name="doc_date", lookup_expr="gte")
    doc_date_to = django_filters.DateFilter(field_name="doc_date", lookup_expr="lte")
    due_date_to = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    payment_state = django_filters.ChoiceFilter(
        choices=[("UNPAID", "UNPAID"), ("PARTIAL", "PARTIAL"), ("PAID", "PAID"), ("OPEN", "OPEN")],
        method="filter_payment_state",
    )
    q = django_filters.CharFilter(field_name="doc_number", lookup_expr="icontains")

    class Meta:
        model = Document
        fields: tuple[str, ...] = ()

    def filter_book(self, qs: QuerySet[Document], name: str, value: str) -> QuerySet[Document]:
        return qs if value == "ALL" else qs.filter(is_gst_document=(value == "GST"))

    def filter_payment_state(
        self, qs: QuerySet[Document], name: str, value: str
    ) -> QuerySet[Document]:
        if value == "UNPAID":
            return qs.filter(amount_settled=0)
        if value == "PAID":
            return qs.filter(amount_settled__gte=F("net_receivable"), net_receivable__gt=0)
        if value == "OPEN":  # anything still owed: unpaid or part paid
            return qs.filter(amount_settled__lt=F("net_receivable"))
        return qs.filter(Q(amount_settled__gt=0) & Q(amount_settled__lt=F("net_receivable")))


class DocumentListView(ActionAPIView):
    write_action = DRAFT
    serializer_class = DocumentListSerializer
    filterset_class = DocumentFilter
    ordering_fields = ("doc_date", "doc_number", "created_at")

    def get_queryset(self) -> Any:
        return Document.objects.select_related("party", "project")  # names, one query

    @extend_schema(responses={200: DocumentListSerializer(many=True)}, tags=["documents"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), DocumentListSerializer)

    @extend_schema(
        request=DocumentWriteSerializer, responses={201: DocumentSerializer}, tags=["documents"]
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = DocumentWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        doc = drafts.create_draft(self.principal, data.validated_data)
        return detail_response(doc, DocumentSerializer, status=201)


class DocumentDetailView(ActionAPIView):
    write_action = DRAFT

    @extend_schema(responses={200: DocumentSerializer}, tags=["documents"])
    def get(self, request: Request, document_id: uuid.UUID) -> Response:
        return detail_response(drafts.get_document(self.principal, document_id), DocumentSerializer)

    @extend_schema(
        request=DocumentWriteSerializer, responses={200: DocumentSerializer}, tags=["documents"]
    )
    def patch(self, request: Request, document_id: uuid.UUID) -> Response:
        return versioned_patch(
            request,
            load=lambda: drafts.get_document(self.principal, document_id),
            input_serializer=DocumentWriteSerializer,
            update=lambda v, changes: drafts.update_draft(self.principal, document_id, v, changes),
            output_serializer=DocumentSerializer,
        )

    @extend_schema(responses={204: None}, tags=["documents"])
    def delete(self, request: Request, document_id: uuid.UUID) -> Response:
        drafts.delete_draft(self.principal, document_id)
        return Response(status=204)


class ParseLinesView(ActionAPIView):
    """Lines for a draft from a CSV / XLSX file or pasted cells (B.7): checked, not saved."""

    read_action = DRAFT
    write_action = DRAFT
    parser_classes = (JSONParser, MultiPartParser)

    @extend_schema(
        request={
            "application/json": ParseLinesRequestSerializer,
            "multipart/form-data": ParseLinesRequestSerializer,
        },
        responses={200: ParseLinesResultSerializer},
        tags=["documents"],
    )
    def post(self, request: Request) -> Response:
        params = ParseLinesRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        upload = params.validated_data.get("file")
        lines, sheet = line_import.parse_lines(
            self.principal,
            data=upload_bytes(upload) if upload is not None else None,
            text=params.validated_data.get("text"),
        )
        rows = [
            {
                "description": ln["description"],
                "sac_hsn": ln.get("sac_hsn"),
                "unit": ln.get("unit"),
                "quantity": ln["quantity"],
                "rate": ln["rate"],
                "discount_amount": ln.get("discount_amount"),
                "discount_pct": ln.get("discount_pct"),
                "gst_rate": ln.get("gst_rate"),
            }
            for ln in lines
        ]
        return Response(
            ParseLinesResultSerializer(
                {
                    "dry_run": True,
                    "count": len(rows),
                    "skipped_rows": sheet.skipped_rows,
                    "ignored_columns": sheet.ignored_columns,
                    "lines": rows,
                }
            ).data
        )


class LastRatesView(ActionAPIView):
    """The rate last charged to this client for each catalog item (B.8)."""

    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: LastRatesSerializer}, tags=["documents"])
    def get(self, request: Request, party_id: uuid.UUID) -> Response:
        rows = rates.last_rates(self.principal, party_id)
        return Response({"results": LastRateSerializer(rows, many=True).data})


class LinesSampleView(ActionAPIView):
    """A sample file of bill lines to fill in."""

    read_action = DRAFT

    @extend_schema(
        parameters=[SampleQuerySerializer],
        responses={(200, "application/octet-stream"): bytes},
        tags=["documents"],
    )
    def get(self, request: Request) -> HttpResponseBase:
        q = SampleQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        return sample_response(line_import.LAYOUT, q.validated_data["type"], "lines-sample")


class PreviewTotalsView(ActionAPIView):
    """Live totals while the user types: nothing is saved."""

    read_action = DRAFT
    write_action = DRAFT

    @extend_schema(
        request=DocumentWriteSerializer, responses={200: PreviewSerializer}, tags=["documents"]
    )
    def post(self, request: Request) -> Response:
        data = DocumentWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        c = drafts.preview(self.principal, data.validated_data)
        lines = [
            {
                **{k: str(v) for k, v in out.__dict__.items()},
                "line_no": i,
                **(
                    {"prev_cumulative_qty": f"{ln['prev_cumulative_qty']:.3f}"}
                    if ln.get("prev_cumulative_qty") is not None
                    else {}
                ),
            }
            for i, (ln, out) in enumerate(zip(c.lines, c.out.lines, strict=True), start=1)
        ]
        return Response(
            {
                "place_of_supply": c.resolved.place_of_supply,
                "supply_type": c.out.supply_type,
                "supply_category": c.resolved.supply_category,
                "lut": c.lut,
                "reverse_charge": c.reverse_charge,
                "totals": TotalsSerializer(c.out).data,
                "lines": lines,
            }
        )


# --- lifecycle (Phase 1.6) -------------------------------------------------------------


class _DocumentAction(ActionAPIView):
    read_action = "documents.issue"
    write_action = "documents.issue"

    def _load(self, document_id: uuid.UUID) -> Document:
        return drafts.get_document(self.principal, document_id)


class IssueView(_DocumentAction):
    @extend_schema(request=None, responses={200: DocumentSerializer}, tags=["documents"])
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        return versioned_action(
            request,
            load=lambda: self._load(document_id),
            run=lambda v: lifecycle.issue(self.principal, document_id, v),
            output_serializer=DocumentSerializer,
        )


class CancelView(_DocumentAction):
    @extend_schema(
        request=CancelSerializer, responses={200: DocumentSerializer}, tags=["documents"]
    )
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        data = CancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return versioned_action(
            request,
            load=lambda: self._load(document_id),
            run=lambda v: lifecycle.cancel(
                self.principal, document_id, v, data.validated_data["reason"]
            ),
            output_serializer=DocumentSerializer,
        )


class AcceptView(_DocumentAction):
    accept = True

    @extend_schema(request=None, responses={200: DocumentSerializer}, tags=["documents"])
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        return versioned_action(
            request,
            load=lambda: self._load(document_id),
            run=lambda v: lifecycle.respond_to_quotation(
                self.principal, document_id, v, accept=self.accept
            ),
            output_serializer=DocumentSerializer,
        )


class DeclineView(AcceptView):
    accept = False


class ConvertView(ActionAPIView):
    write_action = DRAFT

    @extend_schema(
        request=ConvertSerializer, responses={201: DocumentSerializer}, tags=["documents"]
    )
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        data = ConvertSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = lifecycle.convert(
            self.principal, document_id, data.validated_data["to"], data.validated_data["doc_date"]
        )
        return detail_response(draft, DocumentSerializer, status=201)


class DuplicateView(ActionAPIView):
    """A new draft copied from a bill or quotation (B.10)."""

    write_action = DRAFT

    @extend_schema(
        request=DuplicateSerializer, responses={201: DocumentSerializer}, tags=["documents"]
    )
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        data = DuplicateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = lifecycle.duplicate(self.principal, document_id, data.validated_data["doc_date"])
        return detail_response(draft, DocumentSerializer, status=201)


class CreditNoteView(ActionAPIView):
    write_action = DRAFT
    note_type = "CREDIT_NOTE"

    @extend_schema(request=NoteSerializer, responses={201: DocumentSerializer}, tags=["documents"])
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        data = NoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        note = lifecycle.create_note(
            self.principal,
            document_id,
            self.note_type,
            v["doc_date"],
            v.get("lines"),
            v.get("notes"),
        )
        return detail_response(note, DocumentSerializer, status=201)


class DebitNoteView(CreditNoteView):
    note_type = "DEBIT_NOTE"


# --- PDF (Phase 1.7) ---------------------------------------------------------------------


class DocumentPdfView(ActionAPIView):
    """Issued: 302 to a short-lived link (202 while it is being made).
    Draft: rendered on demand with a DRAFT watermark, never stored."""

    write_action = DRAFT

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "as",
                str,
                enum=["link"],
                description="`link`: answer 200 {url, expires_in} instead of a 302, for"
                " clients that cannot read a cross-origin redirect (browsers). Issued only.",
            )
        ],
        responses={
            (200, "application/pdf"): bytes,
            (200, "application/json"): PdfLinkSerializer,
            302: None,
            202: {"type": "object", "properties": {"status": {"type": "string"}}},
        },
        tags=["documents"],
    )
    def get(self, request: Request, document_id: uuid.UUID) -> HttpResponseBase:
        doc = drafts.get_document(self.principal, document_id)
        as_link = request.query_params.get("as") == "link"
        if doc.status == "DRAFT" and as_link:
            raise Invalid("as", "Drafts are rendered on demand: ask without as=link.", code="draft")
        if doc.status == "DRAFT":
            return HttpResponse(
                render_pdf(doc),
                content_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{pdfs.pdf_filename(doc)}"'},
            )
        attachment = (
            Attachment.objects.filter(pk=doc.pdf_attachment_id, status="AVAILABLE").first()
            if doc.pdf_attachment_id
            else None
        )
        if attachment is None:
            pdfs.enqueue_pdf(self.principal.tenant_id, self.principal.user_id, doc.pk)
            return Response({"status": "rendering"}, status=202, headers={"Retry-After": "3"})
        url = storage.download_url(attachment.storage_key, attachment.original_filename)
        if as_link:
            return Response({"url": url, "expires_in": storage.DOWNLOAD_URL_TTL})
        return HttpResponseRedirect(url)
