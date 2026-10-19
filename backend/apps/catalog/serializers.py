from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField, PercentField

from .models import CatalogItem


class CatalogItemSerializer(serializers.ModelSerializer[CatalogItem]):
    default_rate = MoneyField(allow_null=True)
    gst_rate = PercentField()

    class Meta:
        model = CatalogItem
        fields = (
            "id",
            "name",
            "description",
            "unit",
            "sac_hsn",
            "default_rate",
            "gst_rate",
            "is_active",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CatalogItemWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(min_length=1, max_length=200)
    description = serializers.CharField(max_length=2000, required=False, allow_null=True)
    unit = serializers.CharField(max_length=20, required=False, allow_null=True)
    sac_hsn = serializers.RegexField(r"^[0-9]{4,8}$", required=False, allow_null=True)
    default_rate = MoneyField(required=False, allow_null=True, min_value=Decimal("0"))
    gst_rate = PercentField(default=Decimal("18"), max_value=Decimal("50"))
    is_active = serializers.BooleanField(default=True)
