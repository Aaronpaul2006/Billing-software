from typing import Any

from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer[Notification]):
    class Meta:
        model = Notification
        fields = ("id", "kind", "title", "body", "link", "read_at", "created_at")
        read_only_fields = fields


class UnreadSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()


class NotificationQuerySerializer(serializers.Serializer[Any]):
    unread = serializers.BooleanField(required=False, help_text="Only those not read yet")
