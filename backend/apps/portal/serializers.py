"""Client-portal responses (W.5b). Explicit fields, and fewer than the staff
API: nothing about our registrations, series, catalog or who did what."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.documents.models import Document, DocumentLine
from apps.documents.serializers import LineOutSerializer, TotalsSerializer
from apps.payments.models import Allocation, Payment
from apps.payments.serializers import payment_allocations


class PortalBusinessSerializer(serializers.Serializer[Any]):
    legal_name = serializers.CharField()
    trade_name = serializers.CharField(allow_null=True)


class PortalClientSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    display_name = serializers.CharField()
    gstin = serializers.CharField(allow_null=True)


class PortalMeSerializer(serializers.Serializer[Any]):
    business = PortalBusinessSerializer(help_text="Whose portal this is: the contractor.")
    client = PortalClientSerializer(help_text="The client the signed-in person belongs to.")


class PortalDocumentSerializer(serializers.ModelSerializer[Document]):
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
            "due_date",
            "valid_until",
            "project_id",
            "project_name",
            "is_gst_document",
            "is_ra_bill",
            "ra_sequence",
            "totals",
            "issued_at",
        )
        read_only_fields: tuple[str, ...] = fields


class PortalLineSerializer(LineOutSerializer):
    """A bill line without our catalog references."""

    catalog_item_id = None  # type: ignore[assignment]
    catalog_variant_id = None  # type: ignore[assignment]

    class Meta(LineOutSerializer.Meta):
        fields = (  # type: ignore[assignment]
            "line_no",
            "boq_item_id",
            "description",
            "sac_hsn",
            "unit",
            "quantity",
            "prev_cumulative_qty",
            "up_to_date_qty",
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
        read_only_fields = fields  # type: ignore[assignment]


class PortalDocumentDetailSerializer(PortalDocumentSerializer):
    lines = serializers.SerializerMethodField()

    class Meta(PortalDocumentSerializer.Meta):
        fields = (*PortalDocumentSerializer.Meta.fields, "place_of_supply", "terms", "lines")
        read_only_fields = fields

    @extend_schema_field(PortalLineSerializer(many=True))
    def get_lines(self, obj: Document) -> list[dict[str, Any]]:
        lines = DocumentLine.objects.filter(document_id=obj.pk).order_by("line_no")
        return list(PortalLineSerializer(lines, many=True).data)


class PortalAllocationSerializer(serializers.ModelSerializer[Allocation]):
    document_id = serializers.UUIDField(allow_null=True)
    doc_number = serializers.SerializerMethodField()
    retention_release_id = serializers.UUIDField(allow_null=True)
    amount = MoneyField()

    class Meta:
        model = Allocation
        fields = ("document_id", "doc_number", "retention_release_id", "amount")
        read_only_fields = fields

    def get_doc_number(self, obj: Allocation) -> str | None:
        return obj.document.doc_number if obj.document_id else None


class PortalPaymentSerializer(serializers.ModelSerializer[Payment]):
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    amount = MoneyField()
    allocations = serializers.SerializerMethodField(help_text="The bills this payment settled.")

    class Meta:
        model = Payment
        fields = (
            "id",
            "payment_date",
            "amount",
            "mode",
            "reference",
            "project_id",
            "project_name",
            "allocations",
        )
        read_only_fields = fields

    @extend_schema_field(PortalAllocationSerializer(many=True))
    def get_allocations(self, obj: Payment) -> list[dict[str, Any]]:
        return list(PortalAllocationSerializer(payment_allocations(obj), many=True).data)


class PortalProjectSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()
    contract_value = MoneyField(allow_null=True)
    start_date = serializers.DateField(allow_null=True)
    end_date = serializers.DateField(allow_null=True)


class PortalProjectListSerializer(serializers.Serializer[Any]):
    results = PortalProjectSerializer(many=True)
