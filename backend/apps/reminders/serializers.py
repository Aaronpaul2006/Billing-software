from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField

from .models import PaymentReminder, ReminderStage


class PaymentReminderSerializer(serializers.ModelSerializer[PaymentReminder]):
    document_id = serializers.UUIDField()
    stage = serializers.ChoiceField(choices=ReminderStage.choices)
    amount_due = MoneyField()
    sent_by_name = serializers.SerializerMethodField(help_text="null: the daily job.")

    class Meta:
        model = PaymentReminder
        fields = ("id", "document_id", "stage", "sent_to", "amount_due", "sent_by_name", "sent_at")
        read_only_fields = fields

    def get_sent_by_name(self, obj: PaymentReminder) -> str | None:
        return obj.sent_by.full_name if obj.sent_by_id and obj.sent_by else None


class PaymentReminderListSerializer(serializers.Serializer[Any]):
    results = PaymentReminderSerializer(many=True)
