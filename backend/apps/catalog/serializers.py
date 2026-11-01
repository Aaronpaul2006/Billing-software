from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.fields import MoneyField, PercentField

from .models import CatalogItem, CatalogItemVariant


class CatalogVariantSerializer(serializers.ModelSerializer[CatalogItemVariant]):
    catalog_item_id = serializers.UUIDField()
    rate_delta = MoneyField(help_text="Added to the item's default rate (may be negative).")

    class Meta:
        model = CatalogItemVariant
        fields = (
            "id",
            "catalog_item_id",
            "attribute",
            "value",
            "rate_delta",
            "is_active",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CatalogVariantListSerializer(serializers.Serializer[Any]):
    results = CatalogVariantSerializer(many=True)


class CatalogVariantWriteSerializer(serializers.Serializer[Any]):
    attribute = serializers.CharField(min_length=1, max_length=50, help_text="e.g. Brand")
    value = serializers.CharField(min_length=1, max_length=100, help_text="e.g. UltraTech")
    rate_delta = MoneyField(default=Decimal("0.00"))
    is_active = serializers.BooleanField(default=True)


class CatalogItemSerializer(serializers.ModelSerializer[CatalogItem]):
    default_rate = MoneyField(allow_null=True)
    gst_rate = PercentField()
    variants = serializers.SerializerMethodField()

    @extend_schema_field(CatalogVariantSerializer(many=True))
    def get_variants(self, obj: CatalogItem) -> list[dict[str, Any]]:
        rows = getattr(obj, "prefetched_variants", None)
        if rows is None:
            rows = CatalogItemVariant.objects.filter(catalog_item_id=obj.pk).order_by(
                "attribute", "value"
            )
        return list(CatalogVariantSerializer(rows, many=True).data)

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
            "variants",
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
