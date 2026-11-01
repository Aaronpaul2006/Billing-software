"""Payment reminders on a bill: the history, and "send one now" (W.2)."""

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView
from apps.core.idempotency import idempotent

from . import services
from .serializers import PaymentReminderListSerializer, PaymentReminderSerializer


class DocumentRemindersView(ActionAPIView):
    write_action = services.SEND
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: PaymentReminderListSerializer}, tags=["reminders"])
    def get(self, request: Request, document_id: uuid.UUID) -> Response:
        rows = services.history(self.principal, document_id)
        return Response({"results": PaymentReminderSerializer(rows, many=True).data})

    @extend_schema(request=None, responses={201: PaymentReminderSerializer}, tags=["reminders"])
    @idempotent
    def post(self, request: Request, document_id: uuid.UUID) -> Response:
        reminder = services.send_now(self.principal, document_id)
        return Response(PaymentReminderSerializer(reminder).data, status=201)
