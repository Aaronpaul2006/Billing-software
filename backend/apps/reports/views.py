"""Dashboard and reporting endpoints (docs/02-api-design.md §8).

Read-only; `reports.view` (OWNER, ADMIN, ACCOUNTANT, VIEWER). Amounts are
strings. The mobile app uses the same endpoints and permissions.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView
from apps.core.queries import get_or_404
from apps.parties.models import Party
from apps.projects.models import Project

from . import cashflow, dashboard, queries
from .serializers import (
    CashFlowParamsSerializer,
    CashFlowSerializer,
    DashboardSerializer,
    GstPeriodSerializer,
    GstRowSerializer,
    GstSummaryReportSerializer,
    GstTotalsSerializer,
    MonthSerializer,
    MonthsSerializer,
    PeriodSerializer,
    ProjectReportSerializer,
    ProjectReportsSerializer,
    ReceivableSerializer,
    ReceivablesSerializer,
    ReportTotalsSerializer,
    StatementSerializer,
    SummarySerializer,
    TdsParamsSerializer,
    TdsReconciliationSerializer,
    fy_start,
    previous_period,
)
from .statement import build_statement

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


class DashboardView(ReportView):
    """The main dashboard (W.6), in one request."""

    @extend_schema(parameters=PERIOD_PARAMS, responses={200: DashboardSerializer}, tags=["reports"])
    def get(self, request: Request) -> Response:
        p = self.period(request)
        previous = previous_period(p["start"], p["end"])
        data = dashboard.dashboard(
            self.principal.tenant_id, p["start"], p["end"], p["book"], previous
        )
        return Response(DashboardSerializer(data).data)


class BillingByMonthView(ReportView):
    @extend_schema(parameters=PERIOD_PARAMS, responses={200: MonthsSerializer}, tags=["reports"])
    def get(self, request: Request) -> Response:
        p = self.period(request)
        rows = queries.billing_by_month(self.principal.tenant_id, p["start"], p["end"], p["book"])
        return Response({"results": MonthSerializer(rows, many=True).data})


class ReceivablesView(ReportView):
    @extend_schema(
        parameters=PERIOD_PARAMS[2:],
        responses={200: ReceivablesSerializer},
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
    @extend_schema(
        operation_id="reports_projects_list",
        responses={200: ProjectReportsSerializer},
        tags=["reports"],
    )
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
        responses={200: GstSummaryReportSerializer},
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
                "totals": GstTotalsSerializer(totals).data,
            }
        )


# Form 16A: 15 days after the quarterly TDS return is due (31 Jul, 31 Oct, 31 Jan, 31 May).
CERTIFICATE_DUE = {1: (0, 8, 15), 2: (0, 11, 15), 3: (1, 2, 15), 4: (1, 6, 15)}


def tds_status(difference: Decimal, certified: Decimal) -> str:
    if difference == 0:
        return "MATCHED"
    if certified == 0:
        return "NOT_RECEIVED"
    return "SHORT" if difference < 0 else "EXCESS"


class TdsReconciliationView(ReportView):
    @extend_schema(
        parameters=[TdsParamsSerializer],
        responses={200: TdsReconciliationSerializer},
        tags=["reports"],
    )
    def get(self, request: Request) -> Response:
        params = TdsParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        today = timezone.localdate()
        fy = params.validated_data.get("fy") or fy_start(today).year
        rows = queries.tds_reconciliation(
            self.principal.tenant_id, fy, params.validated_data.get("party_id")
        )
        for row in rows:
            row["difference"] = row["certified"] - row["expected"]
            row["status"] = tds_status(row["difference"], row["certified"])
            years, month, day = CERTIFICATE_DUE[row["quarter"]]
            row["certificate_due"] = date(fy + years, month, day)
            row["overdue"] = (
                row["status"] in ("SHORT", "NOT_RECEIVED") and today > row["certificate_due"]
            )
        totals = {
            k: sum((r[k] for r in rows), Decimal("0.00"))
            for k in ("expected", "certified", "difference")
        }
        return Response(
            TdsReconciliationSerializer(
                {"fy_start_year": fy, "results": rows, "totals": totals}
            ).data
        )


class StatementView(ReportView):
    """A client's statement of account between `from` and `to` (default: this FY to today)."""

    @extend_schema(
        parameters=PERIOD_PARAMS[:2],
        responses={200: StatementSerializer},
        tags=["reports"],
    )
    def get(self, request: Request, party_id: uuid.UUID) -> Response:
        party = get_or_404(Party, party_id)  # unknown or another tenant's: 404
        p = self.period(request)
        statement = build_statement(self.principal.tenant_id, party.pk, p["start"], p["end"])
        statement["party"] = {
            "id": party.pk,
            "display_name": party.display_name,
            "gstin": party.gstin,
        }
        return Response(StatementSerializer(statement).data)


class CashFlowView(ReportView):
    """The next weeks' money in and out, as ranges (Part B, cashflow.py)."""

    @extend_schema(
        parameters=[CashFlowParamsSerializer],
        responses={200: CashFlowSerializer},
        tags=["reports"],
    )
    def get(self, request: Request) -> Response:
        params = CashFlowParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = cashflow.forecast(
            self.principal.tenant_id, timezone.localdate(), params.validated_data["weeks"]
        )
        return Response(CashFlowSerializer(data).data)
