from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField, PercentField, QuantityField

from .models import Document, DocumentLine
from .services.drafts import DRAFTABLE_TYPES

# --- input ---------------------------------------------------------------------------------


class LineInSerializer(serializers.Serializer[Any]):
    """A line. Description, unit, SAC/HSN, rate and GST rate may be left out
    when the line names a catalog or BOQ item: they are filled from it."""

    catalog_item_id = serializers.UUIDField(required=False, allow_null=True)
    boq_item_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(max_length=2000, required=False)
    sac_hsn = serializers.RegexField(r"^[0-9]{4,8}$", required=False, allow_null=True)
    unit = serializers.CharField(max_length=20, required=False, allow_null=True)
    quantity = QuantityField(min_value=Decimal("0.001"))
    rate = MoneyField(required=False, min_value=Decimal("0"))
    discount_amount = MoneyField(required=False, min_value=Decimal("0"))
    gst_rate = PercentField(required=False, max_value=Decimal("50"))


class DocumentWriteSerializer(serializers.Serializer[Any]):
    """Never tax amounts, totals, place of supply or supply type: the server
    derives those (docs/02-api-design.md §5)."""

    doc_type = serializers.ChoiceField(choices=DRAFTABLE_TYPES)
    gst_registration_id = serializers.UUIDField(required=False, allow_null=True)
    party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    doc_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)
    round_to_rupee = serializers.BooleanField(required=False)
    notes = serializers.CharField(
        max_length=5000, required=False, allow_null=True, allow_blank=True
    )
    terms = serializers.CharField(
        max_length=5000, required=False, allow_null=True, allow_blank=True
    )
    lines = LineInSerializer(many=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.partial:
            return attrs  # PATCH: rules are checked on the merged document (service)
        if attrs.get("valid_until") and attrs["doc_type"] != "QUOTATION":
            raise serializers.ValidationError(
                {"valid_until": "Only quotations have a validity date."}, code="not_allowed"
            )
        if attrs.get("due_date") and attrs["due_date"] < attrs["doc_date"]:
            raise serializers.ValidationError(
                {"due_date": "Due before the document date."}, code="invalid_dates"
            )
        return attrs


# --- output --------------------------------------------------------------------------------


class LineOutSerializer(serializers.ModelSerializer[DocumentLine]):
    catalog_item_id = serializers.UUIDField(allow_null=True)
    boq_item_id = serializers.UUIDField(allow_null=True)
    quantity = QuantityField()
    rate = MoneyField()
    discount_amount = MoneyField()
    taxable_value = MoneyField()
    gst_rate = PercentField()
    cgst_amount = MoneyField()
    sgst_amount = MoneyField()
    igst_amount = MoneyField()
    cess_amount = MoneyField()
    line_total = MoneyField()

    class Meta:
        model = DocumentLine
        fields = (
            "line_no",
            "catalog_item_id",
            "boq_item_id",
            "description",
            "sac_hsn",
            "unit",
            "quantity",
            "rate",
            "discount_amount",
            "taxable_value",
            "gst_rate",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "cess_amount",
            "line_total",
        )
        read_only_fields = fields


class TotalsSerializer(serializers.Serializer[Any]):
    subtotal = MoneyField()
    cgst = MoneyField(source="cgst_amount")
    sgst = MoneyField(source="sgst_amount")
    igst = MoneyField(source="igst_amount")
    cess = MoneyField(source="cess_amount")
    round_off = MoneyField()
    grand_total = MoneyField()
    retention = MoneyField(source="retention_amount")
    income_tax_tds = MoneyField(source="income_tax_tds_amount")
    gst_tds = MoneyField(source="gst_tds_amount")
    advance_recovery = MoneyField(source="advance_recovery_amount")
    net_receivable = MoneyField()
    amount_settled = MoneyField(required=False)
    outstanding = serializers.SerializerMethodField()

    def get_outstanding(self, obj: Any) -> str:
        settled = getattr(obj, "amount_settled", Decimal("0.00"))
        return f"{obj.net_receivable - settled:.2f}"


class DocumentListSerializer(serializers.ModelSerializer[Document]):
    gst_registration_id = serializers.UUIDField()
    party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(allow_null=True)
    totals = TotalsSerializer(source="*")

    class Meta:
        model = Document
        fields: tuple[str, ...] = (
            "id",
            "version",
            "doc_type",
            "status",
            "doc_number",
            "doc_date",
            "fy_start_year",
            "due_date",
            "valid_until",
            "gst_registration_id",
            "party_id",
            "project_id",
            "place_of_supply",
            "supply_type",
            "is_gst_document",
            "round_to_rupee",
            "totals",
            "issued_at",
            "created_at",
            "updated_at",
        )
        read_only_fields: tuple[str, ...] = fields


class DocumentSerializer(DocumentListSerializer):
    lines = serializers.SerializerMethodField()

    class Meta(DocumentListSerializer.Meta):
        fields = (*DocumentListSerializer.Meta.fields, "notes", "terms", "lines")
        read_only_fields = fields

    def get_lines(self, obj: Document) -> list[dict[str, Any]]:
        lines = DocumentLine.objects.filter(document_id=obj.pk).order_by("line_no")
        return list(LineOutSerializer(lines, many=True).data)


class PreviewSerializer(serializers.Serializer[Any]):
    place_of_supply = serializers.CharField()
    supply_type = serializers.CharField()
    totals = TotalsSerializer()
    lines = serializers.ListField(child=serializers.DictField())
