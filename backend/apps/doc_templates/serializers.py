from decimal import Decimal
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.core.fields import MoneyField, PercentField, QuantityField

from .models import TEMPLATE_TYPES, DocumentTemplate


class TemplateLineSerializer(serializers.Serializer[Any]):
    """A line as typed: no catalog or BOQ link (a template outlives both)."""

    description = serializers.CharField(min_length=1, max_length=2000)
    sac_hsn = serializers.RegexField(r"^[0-9]{4,8}$", required=False, allow_null=True)
    unit = serializers.CharField(max_length=20, required=False, allow_null=True)
    quantity = QuantityField(min_value=Decimal("0.001"))
    rate = MoneyField(min_value=Decimal("0"))
    discount_amount = MoneyField(min_value=Decimal("0"), default=Decimal("0.00"))
    gst_rate = PercentField(max_value=Decimal("50"))


class TemplateSerializer(serializers.ModelSerializer[DocumentTemplate]):
    lines = TemplateLineSerializer(many=True)

    class Meta:
        model = DocumentTemplate
        fields = (
            "id",
            "version",
            "name",
            "doc_type",
            "valid_days",
            "notes",
            "terms",
            "lines",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TemplateWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(min_length=1, max_length=100)
    doc_type = serializers.ChoiceField(choices=TEMPLATE_TYPES, default="QUOTATION")
    valid_days = serializers.IntegerField(
        min_value=1,
        max_value=365,
        required=False,
        allow_null=True,
        help_text="Quotations: valid until = the date + this many days.",
    )
    notes = serializers.CharField(
        max_length=5000, required=False, allow_null=True, allow_blank=True
    )
    terms = serializers.CharField(
        max_length=5000, required=False, allow_null=True, allow_blank=True
    )
    lines: serializers.ListSerializer[Any] = serializers.ListSerializer(
        child=TemplateLineSerializer(), min_length=1, max_length=200
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """On PATCH the rule is checked on the stored template plus the changes."""
        stored: DocumentTemplate | None = self.context.get("instance")
        doc_type = attrs.get("doc_type") or (stored.doc_type if stored else "QUOTATION")
        if attrs.get("valid_days") and doc_type != "QUOTATION":
            raise serializers.ValidationError(
                {"valid_days": "Only quotations have a validity."}, code="not_allowed"
            )
        if stored and doc_type != "QUOTATION" and "valid_days" not in attrs:
            attrs["valid_days"] = None  # no longer a quotation: no validity to keep
        return attrs


class SaveAsTemplateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(min_length=1, max_length=100)
    valid_days = serializers.IntegerField(
        min_value=1, max_value=365, required=False, allow_null=True
    )


class UseTemplateSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    doc_date = serializers.DateField(required=False, help_text="Default: today.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs.setdefault("doc_date", timezone.localdate())
        return attrs
