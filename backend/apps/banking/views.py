"""Bank statement endpoints (Part B): import, then match each line."""

import json
import uuid
from typing import Any

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, list_response, versioned_action
from apps.core.errors import Invalid
from apps.core.idempotency import idempotent
from apps.core.imports import upload_bytes
from apps.core.queries import get_or_404

from . import services, statement
from .models import BankLine
from .serializers import (
    BankAccountsSerializer,
    BankLineSerializer,
    IgnoreSerializer,
    MatchSerializer,
    RecordFromLineSerializer,
    StatementImportedSerializer,
    StatementPreviewSerializer,
    StatementUploadSerializer,
)

RECORD = "payments.record"


def _mapping(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise Invalid("mapping", "Not a list of columns.", code="invalid") from exc
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise Invalid("mapping", "Not a list of columns.", code="invalid")
    unknown = set(value) - set(statement.FIELDS)
    if unknown:
        raise Invalid("mapping", f"Unknown: {', '.join(sorted(unknown))}.", code="invalid")
    return {k: v for k, v in value.items() if v}


class StatementPreviewView(ActionAPIView):
    """Read a statement file and show what would be imported; nothing is saved."""

    read_action = RECORD
    write_action = RECORD
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={"multipart/form-data": StatementUploadSerializer},
        responses={200: StatementPreviewSerializer},
        tags=["banking"],
    )
    def post(self, request: Request) -> Response:
        data = StatementUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        s = statement.read(
            upload_bytes(data.validated_data["file"]), _mapping(data.validated_data.get("mapping"))
        )
        return Response(
            StatementPreviewSerializer(
                {
                    "ready": s.ready,
                    "headers": s.headers,
                    "columns": s.columns,
                    "line_count": len(s.lines),
                    "skipped_rows": s.skipped_rows,
                    "lines": s.lines[:20],
                }
            ).data
        )


class StatementImportView(ActionAPIView):
    read_action = RECORD
    write_action = RECORD
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={"multipart/form-data": StatementUploadSerializer},
        responses={201: StatementImportedSerializer},
        tags=["banking"],
    )
    @idempotent
    def post(self, request: Request) -> Response:
        data = StatementUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        label = (data.validated_data.get("account_label") or "").strip()
        if not label:
            raise Invalid(
                "account_label", "Name the bank account, e.g. HDFC current 1234.", code="required"
            )
        done = services.import_statement(
            self.principal,
            upload_bytes(data.validated_data["file"]),
            label,
            _mapping(data.validated_data.get("mapping")),
        )
        return Response(StatementImportedSerializer(done).data, status=201)


class BankLineFilter(django_filters.FilterSet):
    account_label = django_filters.CharFilter(field_name="account_label")
    direction = django_filters.ChoiceFilter(
        choices=[("IN", "IN"), ("OUT", "OUT")], method="filter_direction"
    )
    line_date_from = django_filters.DateFilter(field_name="line_date", lookup_expr="gte")
    line_date_to = django_filters.DateFilter(field_name="line_date", lookup_expr="lte")

    class Meta:
        model = BankLine
        fields = ("status",)

    def filter_direction(self, qs: Any, name: str, value: str) -> Any:
        return qs.filter(money_in__gt=0) if value == "IN" else qs.filter(money_out__gt=0)


class BankLineListView(ActionAPIView):
    """Bank lines, newest first; open lines carry what they may be (suggestions)."""

    read_action = RECORD
    write_action = RECORD
    serializer_class = BankLineSerializer
    filterset_class = BankLineFilter
    ordering_fields = ("line_date",)

    def get_queryset(self) -> Any:
        return BankLine.objects.order_by("-line_date", "-id")

    @extend_schema(responses={200: BankLineSerializer(many=True)}, tags=["banking"])
    def get(self, request: Request) -> Response:
        return list_response(self, self.get_queryset(), BankLineSerializer)


class BankAccountsView(ActionAPIView):
    """The bank accounts lines were imported for (to filter by)."""

    read_action = RECORD
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: BankAccountsSerializer}, tags=["banking"])
    def get(self, request: Request) -> Response:
        labels = sorted(set(BankLine.objects.values_list("account_label", flat=True)))
        return Response({"results": labels})


class _LineAction(ActionAPIView):
    read_action = RECORD
    write_action = RECORD

    def _run(self, request: Request, line_id: uuid.UUID, run: Any) -> Response:
        return versioned_action(
            request,
            load=lambda: get_or_404(BankLine, line_id),
            run=run,
            output_serializer=BankLineSerializer,
        )


class BankLineMatchView(_LineAction):
    @extend_schema(request=MatchSerializer, responses={200: BankLineSerializer}, tags=["banking"])
    def post(self, request: Request, line_id: uuid.UUID) -> Response:
        data = MatchSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return self._run(
            request,
            line_id,
            lambda e: services.match(
                self.principal, line_id, e, v.get("payment_id"), v.get("vendor_payment_id")
            ),
        )


class BankLineRecordView(_LineAction):
    @extend_schema(
        request=RecordFromLineSerializer, responses={200: BankLineSerializer}, tags=["banking"]
    )
    @idempotent
    def post(self, request: Request, line_id: uuid.UUID) -> Response:
        data = RecordFromLineSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._run(
            request,
            line_id,
            lambda e: services.record(self.principal, line_id, e, dict(data.validated_data)),
        )


class BankLineIgnoreView(_LineAction):
    @extend_schema(request=IgnoreSerializer, responses={200: BankLineSerializer}, tags=["banking"])
    def post(self, request: Request, line_id: uuid.UUID) -> Response:
        data = IgnoreSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._run(
            request,
            line_id,
            lambda e: services.ignore(self.principal, line_id, e, data.validated_data.get("note")),
        )


class BankLineReopenView(_LineAction):
    @extend_schema(request=None, responses={200: BankLineSerializer}, tags=["banking"])
    def post(self, request: Request, line_id: uuid.UUID) -> Response:
        return self._run(request, line_id, lambda e: services.reopen(self.principal, line_id, e))
