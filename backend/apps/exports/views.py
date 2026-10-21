"""Export endpoints (docs/02-api-design.md §8). Thin: validate, call a service, respond."""

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core import ratelimit
from apps.core.api import ActionAPIView
from apps.core.idempotency import idempotent_if_keyed

from . import services
from .serializers import ExportListSerializer, ExportRequestSerializer, ExportSerializer


class ExportListView(ActionAPIView):
    """Your latest exports (kept 7 days), or ask for a new one: it is made in the
    background (202); poll it until READY, then download within 5 minutes."""

    read_action = services.EXPORT
    write_action = services.EXPORT

    @extend_schema(
        operation_id="exports_list", responses={200: ExportListSerializer}, tags=["exports"]
    )
    def get(self, request: Request) -> Response:
        rows = services.recent_exports(self.principal)
        return Response({"results": ExportSerializer(rows, many=True).data})

    @extend_schema(
        request=ExportRequestSerializer, responses={202: ExportSerializer}, tags=["exports"]
    )
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        ratelimit.enforce(request, "export_user", str(self.principal.user_id))
        data = ExportRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        export = services.request_export(
            self.principal, kind=v["kind"], file_format=v["format"], params=v["params"]
        )
        return Response(ExportSerializer(export).data, status=202)


class ExportDetailView(ActionAPIView):
    """One of your exports, with a 5-minute download link once READY."""

    read_action = services.EXPORT
    write_action = services.EXPORT

    @extend_schema(responses={200: ExportSerializer}, tags=["exports"])
    def get(self, request: Request, export_id: uuid.UUID) -> Response:
        export = services.get_export(self.principal, export_id)
        response = Response(ExportSerializer(export).data)
        response["Cache-Control"] = "no-store"
        return response
