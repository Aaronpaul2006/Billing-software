from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField, PercentField, QuantityField
from apps.core.serializers import STATE_CHOICES, AddressOutSerializer, AddressSerializer

from .models import BoqItem, Project

FIFTY = Decimal("50")


class ProjectSerializer(serializers.ModelSerializer[Project]):
    client_party_id = serializers.UUIDField()
    client_name = serializers.CharField(
        source="client_party.display_name", read_only=True, help_text="The client's display name."
    )
    gst_registration_id = serializers.UUIDField()
    site_address = AddressOutSerializer(allow_null=True)
    contract_value = MoneyField(allow_null=True)
    retention_pct = PercentField()
    income_tax_tds_pct = PercentField()
    mobilisation_advance = MoneyField()
    advance_recovery_pct = PercentField()

    class Meta:
        model = Project
        fields = (
            "id",
            "code",
            "name",
            "client_party_id",
            "client_name",
            "gst_registration_id",
            "site_address",
            "site_state_code",
            "contract_value",
            "retention_pct",
            "income_tax_tds_pct",
            "gst_tds_applicable",
            "mobilisation_advance",
            "advance_recovery_pct",
            "status",
            "start_date",
            "end_date",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ProjectWriteSerializer(serializers.Serializer[Any]):
    code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$", max_length=30)
    name = serializers.CharField(min_length=1, max_length=200)
    client_party_id = serializers.UUIDField()
    gst_registration_id = serializers.UUIDField()
    site_address = AddressSerializer(required=False, allow_null=True)
    site_state_code = serializers.ChoiceField(
        choices=STATE_CHOICES,
        help_text="Place of supply for works on immovable property (IGST Act s.12(3)).",
    )
    contract_value = MoneyField(required=False, allow_null=True, min_value=Decimal("0"))
    retention_pct = PercentField(default=Decimal("0"))
    income_tax_tds_pct = PercentField(default=Decimal("0"))
    gst_tds_applicable = serializers.BooleanField(default=False)
    mobilisation_advance = MoneyField(default=Decimal("0"), min_value=Decimal("0"))
    advance_recovery_pct = PercentField(default=Decimal("0"))
    status = serializers.ChoiceField(choices=Project.Status.values, default="ACTIVE")
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance: Project | None = self.context.get("instance")
        current = (
            {f: getattr(instance, f) for f in ("site_state_code", "start_date", "end_date")}
            if instance
            else {}
        )
        merged = {**current, **attrs}
        start, end = merged.get("start_date"), merged.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "Ends before it starts."}, code="invalid_dates"
            )
        address = attrs.get("site_address")
        if address and address["state_code"] != merged.get("site_state_code"):
            raise serializers.ValidationError(
                {"site_address": {"state_code": "Must be the site state."}},
                code="state_mismatch",
            )
        return attrs


class BoqItemSerializer(serializers.ModelSerializer[BoqItem]):
    project_id = serializers.UUIDField()
    contract_qty = QuantityField()
    rate = MoneyField()
    gst_rate = PercentField()

    class Meta:
        model = BoqItem
        fields = (
            "id",
            "project_id",
            "item_code",
            "description",
            "unit",
            "sac_hsn",
            "contract_qty",
            "rate",
            "gst_rate",
            "is_variation",
            "sort_order",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class BoqItemWriteSerializer(serializers.Serializer[Any]):
    item_code = serializers.CharField(min_length=1, max_length=30, help_text='e.g. "2.1.3"')
    description = serializers.CharField(min_length=1, max_length=2000)
    unit = serializers.CharField(min_length=1, max_length=20, help_text="cum, sqm, kg, nos")
    sac_hsn = serializers.RegexField(r"^[0-9]{4,8}$", required=False, allow_null=True)
    contract_qty = QuantityField(min_value=Decimal("0"))
    rate = MoneyField(min_value=Decimal("0"))
    gst_rate = PercentField(default=Decimal("18"), max_value=FIFTY)
    is_variation = serializers.BooleanField(default=False)
    sort_order = serializers.IntegerField(default=0)


class BoqImportRequestSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(help_text="CSV (UTF-8) or .xlsx, at most 5 MB and 5,000 rows.")
    dry_run = serializers.BooleanField(
        default=False, help_text="Validate and preview; save nothing."
    )


class BoqImportResultSerializer(serializers.Serializer[Any]):
    dry_run = serializers.BooleanField()
    count = serializers.IntegerField()
    skipped_rows = serializers.ListField(
        child=serializers.IntegerField(), help_text="Heading / subtotal rows (no unit, qty, rate)."
    )
    ignored_columns = serializers.ListField(child=serializers.CharField())
    items = BoqItemSerializer(
        many=True, help_text="In a dry run, a preview: id, created_at and updated_at are null."
    )


class BoqProgressRowSerializer(serializers.Serializer[Any]):
    boq_item_id = serializers.UUIDField()
    item_code = serializers.CharField()
    description = serializers.CharField()
    unit = serializers.CharField()
    rate = MoneyField()
    is_variation = serializers.BooleanField()
    contract_qty = QuantityField()
    billed_qty = QuantityField(help_text="In issued tax invoices and bills of supply.")
    balance_qty = QuantityField(help_text="Negative when a variation item went past contract.")
    contract_value = MoneyField()
    billed_value = MoneyField(help_text="Taxable value billed.")
    progress_pct = PercentField(allow_null=True, help_text="Billed / contract quantity.")


class BoqProgressTotalsSerializer(serializers.Serializer[Any]):
    contract_value = MoneyField()
    billed_value = MoneyField()
    progress_pct = PercentField(allow_null=True, help_text="Billed / contract value.")


class BoqProgressSerializer(serializers.Serializer[Any]):
    results = BoqProgressRowSerializer(many=True)
    totals = BoqProgressTotalsSerializer()
