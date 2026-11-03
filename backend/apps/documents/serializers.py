from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.fields import MoneyField, PercentField, QuantityField

from .models import Document, DocumentLine, SupplyCategory
from .services.drafts import DRAFTABLE_TYPES

# --- input ---------------------------------------------------------------------------------


class LineInSerializer(serializers.Serializer[Any]):
    """A line. Description, unit, SAC/HSN, rate and GST rate may be left out
    when the line names a catalog or BOQ item: they are filled from it."""

    catalog_item_id = serializers.UUIDField(required=False, allow_null=True)
    catalog_variant_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="A variant of catalog_item_id: rate = item rate + the variant's delta.",
    )
    boq_item_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(max_length=2000, required=False)
    sac_hsn = serializers.RegexField(r"^[0-9]{4,8}$", required=False, allow_null=True)
    unit = serializers.CharField(max_length=20, required=False, allow_null=True)
    quantity = QuantityField(min_value=Decimal("0.001"))
    rate = MoneyField(required=False, min_value=Decimal("0"))
    discount_amount = MoneyField(required=False, min_value=Decimal("0"))
    discount_pct = PercentField(
        required=False,
        allow_null=True,
        max_value=Decimal("100"),
        help_text="A discount as a percentage of quantity times rate; when given it sets "
        "discount_amount (rounded to the paisa) and wins over a discount_amount sent with it.",
    )
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
    lut = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="SEZ and export supplies: true = zero-rated without IGST under the"
        " registration's Letter of Undertaking, false = charge IGST. Omitted / null:"
        " under the LUT when the registration has one for the document's financial year.",
    )
    reverse_charge = serializers.BooleanField(
        required=False,
        help_text="The recipient pays the tax (registered clients in India). The tax is"
        " shown but not added to the total.",
    )
    is_ra_bill = serializers.BooleanField(
        required=False,
        help_text="RA (running account) bill against the project's BOQ: every line names a"
        " BOQ item, once. Gets the project's next RA number.",
    )
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
    catalog_variant_id = serializers.UUIDField(allow_null=True)
    boq_item_id = serializers.UUIDField(allow_null=True)
    quantity = QuantityField(help_text="RA bill: the quantity in this bill.")
    prev_cumulative_qty = QuantityField(
        allow_null=True, help_text="RA bill: billed before this bill (snapshot at issue)."
    )
    up_to_date_qty = serializers.SerializerMethodField(help_text="RA bill: previous + this bill.")
    rate = MoneyField()
    discount_amount = MoneyField()
    discount_pct = PercentField(allow_null=True)
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
            "catalog_variant_id",
            "boq_item_id",
            "description",
            "sac_hsn",
            "unit",
            "quantity",
            "prev_cumulative_qty",
            "up_to_date_qty",
            "rate",
            "discount_amount",
            "discount_pct",
            "taxable_value",
            "gst_rate",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "cess_amount",
            "line_total",
        )
        read_only_fields = fields

    def get_up_to_date_qty(self, obj: DocumentLine) -> str | None:
        if obj.prev_cumulative_qty is None:
            return None
        return f"{obj.prev_cumulative_qty + obj.quantity:.3f}"


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
    party_name = serializers.SerializerMethodField(
        help_text="As frozen at issue; the party's current name on drafts."
    )
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
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
            "party_name",
            "project_id",
            "project_name",
            "place_of_supply",
            "supply_type",
            "supply_category",
            "lut",
            "reverse_charge",
            "is_gst_document",
            "round_to_rupee",
            "is_ra_bill",
            "ra_sequence",
            "totals",
            "issued_at",
            "created_at",
            "updated_at",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_party_name(self, obj: Document) -> str:
        snapshot = obj.party_snapshot or {}
        name = snapshot.get("display_name")
        return str(name) if name else obj.party.display_name


class DocumentSerializer(DocumentListSerializer):
    lines = serializers.SerializerMethodField()

    class Meta(DocumentListSerializer.Meta):
        fields = (*DocumentListSerializer.Meta.fields, "notes", "terms", "lines")
        read_only_fields = fields

    @extend_schema_field(LineOutSerializer(many=True))
    def get_lines(self, obj: Document) -> list[dict[str, Any]]:
        lines = DocumentLine.objects.filter(document_id=obj.pk).order_by("line_no")
        return list(LineOutSerializer(lines, many=True).data)


class PreviewLineSerializer(serializers.Serializer[Any]):
    line_no = serializers.IntegerField()
    taxable_value = MoneyField()
    cgst_amount = MoneyField()
    sgst_amount = MoneyField()
    igst_amount = MoneyField()
    cess_amount = MoneyField()
    line_total = MoneyField()
    prev_cumulative_qty = QuantityField(required=False, help_text="RA bill lines only.")


class PreviewSerializer(serializers.Serializer[Any]):
    place_of_supply = serializers.CharField()
    supply_type = serializers.CharField()
    supply_category = serializers.ChoiceField(choices=SupplyCategory.choices)
    lut = serializers.BooleanField()
    reverse_charge = serializers.BooleanField()
    totals = TotalsSerializer()
    lines = PreviewLineSerializer(many=True)


class CancelSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(min_length=3, max_length=500)


class ConvertSerializer(serializers.Serializer[Any]):
    to = serializers.ChoiceField(choices=["PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"])
    doc_date = serializers.DateField(
        help_text="Date of the new document (explicit: no time zone guessing)."
    )


class NoteSerializer(serializers.Serializer[Any]):
    doc_date = serializers.DateField()
    notes = serializers.CharField(
        max_length=5000, required=False, allow_null=True, allow_blank=True
    )
    lines = LineInSerializer(
        many=True, required=False, help_text="Without lines, the invoice's lines are copied."
    )


class PdfLinkSerializer(serializers.Serializer[Any]):
    url = serializers.URLField(help_text="Short-lived link to the stored PDF.")
    expires_in = serializers.IntegerField(help_text="Seconds the link stays valid.")


# --- lines from a spreadsheet or pasted cells (B.7) ----------------------------------------


class ParseLinesRequestSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(
        required=False, help_text="CSV (UTF-8) or .xlsx (multipart/form-data)."
    )
    text = serializers.CharField(
        required=False,
        max_length=200_000,
        trim_whitespace=False,
        help_text="Cells copied from a spreadsheet: rows on lines, cells separated by tabs.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("file" in attrs) == ("text" in attrs):
            raise serializers.ValidationError(
                {"file": "Send a file or pasted text."}, code="required"
            )
        return attrs


class ParsedLineSerializer(serializers.Serializer[Any]):
    description = serializers.CharField()
    sac_hsn = serializers.CharField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    quantity = QuantityField()
    rate = MoneyField()
    discount_amount = MoneyField(allow_null=True)
    discount_pct = PercentField(allow_null=True)
    gst_rate = PercentField(allow_null=True)


class ParseLinesResultSerializer(serializers.Serializer[Any]):
    dry_run = serializers.BooleanField(help_text="Always true: nothing is saved.")
    count = serializers.IntegerField()
    skipped_rows = serializers.ListField(child=serializers.IntegerField())
    ignored_columns = serializers.ListField(child=serializers.CharField())
    lines = ParsedLineSerializer(many=True)


class LastRateSerializer(serializers.Serializer[Any]):
    catalog_item_id = serializers.UUIDField()
    catalog_variant_id = serializers.UUIDField(allow_null=True)
    rate = MoneyField()
    document_id = serializers.UUIDField()
    doc_number = serializers.CharField(allow_null=True)
    doc_date = serializers.DateField()


class LastRatesSerializer(serializers.Serializer[Any]):
    results = LastRateSerializer(
        many=True, help_text="Per catalog item and variant: the rate on the latest issued bill."
    )
