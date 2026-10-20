"""Dashboard and reporting endpoints (docs/02-api-design.md §8).

Read-only; `reports.view` (OWNER, ADMIN, ACCOUNTANT, VIEWER). Amounts are
strings. The mobile app uses the same endpoints and permissions.
"""

import uuid
from decimal import Decimal
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView
from apps.core.queries import get_or_404
from apps.projects.models import Project

from . import queries
from .serializers import (
    GstPeriodSerializer,
    GstRowSerializer,
    MonthSerializer,
    PeriodSerializer,
    ProjectReportSerializer,
    ReceivableSerializer,
    ReportTotalsSerializer,
    SummarySerializer,
    previous_period,
)

PERIOD_PARAMS = [
    OpenApiParameter("from", str, description="YYYY-MM-DD; default 1 April of this FY"),
    OpenApiParameter("to", str, description="YYYY-MM-DD; default today"),
    OpenApiParameter("book", str, enum=["ALL", "GST", "NON_GST"]),
]


class ReportView(ActionAPIView):
    read_action = "reports.view"
    write_action = "reports.view"
    pagination_class = None
    filter_backends = ()

    def period(self, request: Request) -> dict[str, Any]:
        params = PeriodSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        return dict(params.validated_data)


class SummaryView(ReportView):
    @extend_schema(parameters=PERIOD_PARAMS, responses={200: SummarySerializer}, tags=["reports"])
    def get(self, request: Request) -> Response:
        p = self.period(request)
        prev_start, prev_end = previous_period(p["start"], p["end"])
        tenant = self.principal.tenant_id
        current = queries.totals(tenant, p["start"], p["end"], p["book"])
        previous = queries.totals(tenant, prev_start, prev_end, p["book"])
        return Response(
            {
                "book": p["book"],
                "period": {"from": p["start"], "to": p["end"]},
                "previous_period": {"from": prev_start, "to": prev_end},
                "current": ReportTotalsSerializer(current).data,
                "previous": ReportTotalsSerializer(previous).data,
            }
        )


class BillingByMonthView(ReportView):
    @extend_schema(
        parameters=PERIOD_PARAMS, responses={200: MonthSerializer(many=True)}, tags=["reports"]
    )
    def get(self, request: Request) -> Response:
        p = self.period(request)
        rows = queries.billing_by_month(self.principal.tenant_id, p["start"], p["end"], p["book"])
        return Response({"results": MonthSerializer(rows, many=True).data})


class ReceivablesView(ReportView):
    @extend_schema(
        parameters=PERIOD_PARAMS[2:],
        responses={200: ReceivableSerializer(many=True)},
        tags=["reports"],
    )
    def get(self, request: Request) -> Response:
        p = self.period(request)
        rows = queries.receivables(self.principal.tenant_id, p["book"])
        totals = {
            key: sum((r[key] for r in rows), Decimal("0.00"))
            for key in (
                "bucket_not_due",
                "bucket_1_30",
                "bucket_31_60",
                "bucket_61_90",
                "bucket_90_plus",
                "total",
            )
        }
        return Response(
            {
                "results": ReceivableSerializer(rows, many=True).data,
                "totals": ReceivableSerializer(
                    {
                        **totals,
                        "party_id": uuid.UUID(int=0),
                        "display_name": "All parties",
                        "document_count": sum(r["document_count"] for r in rows),
                    }
                ).data,
            }
        )


class ProjectsReportView(ReportView):
    @extend_schema(responses={200: ProjectReportSerializer(many=True)}, tags=["reports"])
    def get(self, request: Request) -> Response:
        rows = queries.projects(self.principal.tenant_id)
        return Response({"results": ProjectReportSerializer(rows, many=True).data})


class ProjectReportView(ReportView):
    @extend_schema(responses={200: ProjectReportSerializer}, tags=["reports"])
    def get(self, request: Request, project_id: uuid.UUID) -> Response:
        get_or_404(Project, project_id)  # unknown or another tenant's: 404
        [row] = queries.projects(self.principal.tenant_id, project_id)
        return Response(ProjectReportSerializer(row).data)


class GstSummaryView(ReportView):
    @extend_schema(
        parameters=[OpenApiParameter("period", str, required=True, description="YYYY-MM")],
        responses={200: GstRowSerializer(many=True)},
        tags=["reports"],
    )
    def get(self, request: Request) -> Response:
        params = GstPeriodSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        p = params.validated_data
        rows = queries.gst_summary(self.principal.tenant_id, p["start"], p["end"])
        totals = {
            k: sum((r[k] for r in rows), Decimal("0.00"))
            for k in ("taxable_value", "cgst", "sgst", "igst", "cess")
        }
        return Response(
            {
                "period": p["period"],
                "results": GstRowSerializer(rows, many=True).data,
                "totals": {k: f"{v:.2f}" for k, v in totals.items()},
            }
        )
