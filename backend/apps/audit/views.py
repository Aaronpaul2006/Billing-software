"""The activity log (Part B): owners and admins (`audit.view`)."""

import zoneinfo
from datetime import datetime, time, timedelta

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView

from .entries import RECORD_TYPES, entries
from .models import AuditLog
from .serializers import AuditEntrySerializer, AuditQuerySerializer

INDIA = zoneinfo.ZoneInfo("Asia/Kolkata")


class AuditLogView(ActionAPIView):
    read_action = "audit.view"
    filter_backends = ()

    @extend_schema(
        parameters=[AuditQuerySerializer],
        responses={200: AuditEntrySerializer(many=True)},
        tags=["audit"],
    )
    def get(self, request: Request) -> Response:
        params = AuditQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        q = params.validated_data
        rows = AuditLog.objects.filter(
            tenant_id=self.principal.tenant_id, table_name__in=list(RECORD_TYPES)
        )
        if "actor_id" in q:
            rows = rows.filter(actor_user_id=q["actor_id"])
        if "record_type" in q:
            rows = rows.filter(table_name=q["record_type"])
        if "record_id" in q:
            rows = rows.filter(row_id=q["record_id"])
        if "date_from" in q:
            rows = rows.filter(occurred_at__gte=datetime.combine(q["date_from"], time(), INDIA))
        if "date_to" in q:
            end = datetime.combine(q["date_to"], time(), INDIA) + timedelta(days=1)
            rows = rows.filter(occurred_at__lt=end)
        page = self.paginate_queryset(rows.order_by("-id"))
        data = AuditEntrySerializer(entries(list(page or [])), many=True).data
        return self.get_paginated_response(data)
