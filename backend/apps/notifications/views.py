"""Notifications (Part B): one's own, newest first; mark them read."""

import uuid
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView, list_response
from apps.core.queries import get_or_404

from .models import Notification
from .serializers import NotificationQuerySerializer, NotificationSerializer, UnreadSerializer

ANY = "tenant.read"


def _mine(view: ActionAPIView) -> Any:
    # The database shows each person only their own rows; say so here too.
    return Notification.objects.filter(user_id=view.principal.user_id)


class NotificationListView(ActionAPIView):
    read_action = ANY
    serializer_class = NotificationSerializer
    ordering_fields = ("created_at",)

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):  # the schema, with nobody signed in
            return Notification.objects.none()
        return _mine(self).order_by("-created_at")

    @extend_schema(
        parameters=[NotificationQuerySerializer],
        responses={200: NotificationSerializer(many=True)},
        tags=["notifications"],
    )
    def get(self, request: Request) -> Response:
        params = NotificationQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        qs = self.get_queryset()
        if params.validated_data.get("unread"):
            qs = qs.filter(read_at__isnull=True)
        return list_response(self, qs, NotificationSerializer)


class UnreadCountView(ActionAPIView):
    """For the bell: how many are not read yet."""

    read_action = ANY
    pagination_class = None
    filter_backends = ()

    @extend_schema(responses={200: UnreadSerializer}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        count = _mine(self).filter(read_at__isnull=True).count()
        return Response(UnreadSerializer({"count": count}).data)


class ReadView(ActionAPIView):
    read_action = ANY
    write_action = ANY

    @extend_schema(request=None, responses={200: NotificationSerializer}, tags=["notifications"])
    def post(self, request: Request, notification_id: uuid.UUID) -> Response:
        get_or_404(Notification, notification_id)  # someone else's is not found
        _mine(self).filter(pk=notification_id, read_at__isnull=True).update(read_at=timezone.now())
        return Response(NotificationSerializer(_mine(self).get(pk=notification_id)).data)


class ReadAllView(ActionAPIView):
    read_action = ANY
    write_action = ANY

    @extend_schema(request=None, responses={200: UnreadSerializer}, tags=["notifications"])
    def post(self, request: Request) -> Response:
        marked = _mine(self).filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response(UnreadSerializer({"count": marked}).data)
