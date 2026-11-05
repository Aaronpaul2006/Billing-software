from typing import Any

from rest_framework import serializers

from .entries import RECORD_TYPES


class AuditQuerySerializer(serializers.Serializer[Any]):
    actor_id = serializers.UUIDField(required=False, help_text="Only what this person did")
    record_type = serializers.ChoiceField(choices=sorted(RECORD_TYPES), required=False)
    record_id = serializers.UUIDField(required=False, help_text="One record's changes")
    date_from = serializers.DateField(required=False, help_text="YYYY-MM-DD, India time")
    date_to = serializers.DateField(required=False, help_text="YYYY-MM-DD, India time")


class AuditEntrySerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    occurred_at = serializers.DateTimeField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor_name = serializers.CharField(
        allow_null=True, help_text="Null: done by the system (a scheduled job)"
    )
    record_type = serializers.ChoiceField(choices=sorted(RECORD_TYPES))
    record_type_label = serializers.CharField()
    record_id = serializers.UUIDField()
    record = serializers.CharField(help_text="The record in words, e.g. 'Tax invoice INV/0002'")
    action = serializers.CharField(
        help_text="added, changed, deleted, or a status: issued, cancelled, voided..."
    )
    changed_fields = serializers.ListField(
        child=serializers.CharField(), help_text="Names of the fields changed (never values)"
    )
