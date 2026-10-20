from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.documents.models import Document

from .models import Allocation, Payment, PaymentMode, RetentionBook, RetentionRelease
from .services import allocated_total

PAISA = Decimal("0.01")


class AllocationInSerializer(serializers.Serializer[Any]):
    """Settles a document or (payments only) a retention release: one of the two."""

    document_id = serializers.UUIDField(required=False)
    retention_release_id = serializers.UUIDField(required=False)
    amount = MoneyField(min_value=PAISA)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("document_id" in attrs) == ("retention_release_id" in attrs):
            raise serializers.ValidationError(
                {"document_id": "Give document_id or retention_release_id."}, code="one_target"
            )
        return attrs


class PaymentCreateSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    payment_date = serializers.DateField()
    amount = MoneyField(min_value=PAISA)
    mode = serializers.ChoiceField(choices=PaymentMode.choices)
    reference = serializers.CharField(
        max_length=100, required=False, allow_null=True, help_text="UTR / cheque number"
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)
    allocations = AllocationInSerializer(many=True, required=False)


class AllocateSerializer(serializers.Serializer[Any]):
    allocations = AllocationInSerializer(many=True, allow_empty=False)


class VoidSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(min_length=3, max_length=500)


class AllocationOutSerializer(serializers.ModelSerializer[Allocation]):
    document_id = serializers.UUIDField(allow_null=True)
    retention_release_id = serializers.UUIDField(allow_null=True)
    payment_id = serializers.UUIDField(allow_null=True)
    credit_note_id = serializers.UUIDField(allow_null=True)
    amount = MoneyField()
    doc_number = serializers.SerializerMethodField()

    class Meta:
        model = Allocation
        fields = (
            "id",
            "document_id",
            "doc_number",
            "retention_release_id",
            "payment_id",
            "credit_note_id",
            "amount",
            "created_at",
        )
        read_only_fields = fields

    def get_doc_number(self, obj: Allocation) -> str | None:
        if obj.document_id is None:
            return None
        number: str | None = (
            Document.objects.filter(pk=obj.document_id).values_list("doc_number", flat=True).first()
        )
        return number


class PaymentSerializer(serializers.ModelSerializer[Payment]):
    party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(allow_null=True)
    amount = MoneyField()
    allocated = serializers.SerializerMethodField()
    unallocated = serializers.SerializerMethodField()
    allocations = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = (
            "id",
            "version",
            "party_id",
            "project_id",
            "payment_date",
            "amount",
            "mode",
            "reference",
            "notes",
            "status",
            "allocated",
            "unallocated",
            "allocations",
            "voided_at",
            "void_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_allocated(self, obj: Payment) -> str:
        return f"{allocated_total(obj.pk):.2f}"

    def get_unallocated(self, obj: Payment) -> str:
        if obj.status != "RECORDED":
            return "0.00"
        return f"{obj.amount - allocated_total(obj.pk):.2f}"

    def get_allocations(self, obj: Payment) -> list[dict[str, Any]]:
        rows = Allocation.objects.filter(payment_id=obj.pk).order_by("created_at")
        return list(AllocationOutSerializer(rows, many=True).data)


class DocumentAllocationsSerializer(serializers.Serializer[Any]):
    document_id = serializers.UUIDField()
    doc_type = serializers.CharField()
    applied = MoneyField(allow_null=True, help_text="Credit notes: total applied to invoices.")
    unapplied = MoneyField(allow_null=True, help_text="Credit notes: still available.")
    allocations = AllocationOutSerializer(many=True)


# --- retention releases (Phase 3.3) ------------------------------------------------------


class ReleaseCreateSerializer(serializers.Serializer[Any]):
    project_id = serializers.UUIDField()
    book = serializers.ChoiceField(
        choices=RetentionBook.choices,
        required=False,
        help_text="Whose retention: GST (tax invoices) or NON_GST (bills of supply)."
        " Default: GST while any is held there.",
    )
    release_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    amount = MoneyField(min_value=PAISA)
    reference = serializers.CharField(
        max_length=50, required=False, allow_null=True, help_text="e.g. the client's letter"
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("due_date") and attrs["due_date"] < attrs["release_date"]:
            raise serializers.ValidationError(
                {"due_date": "Due before the release date."}, code="invalid_dates"
            )
        return attrs


class CancelReleaseSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(min_length=3, max_length=500)


class RetentionReleaseSerializer(serializers.ModelSerializer[RetentionRelease]):
    project_id = serializers.UUIDField()
    party_id = serializers.UUIDField()
    amount = MoneyField()
    amount_settled = MoneyField()
    outstanding = serializers.SerializerMethodField()

    class Meta:
        model = RetentionRelease
        fields: tuple[str, ...] = (
            "id",
            "version",
            "project_id",
            "party_id",
            "book",
            "release_date",
            "due_date",
            "amount",
            "amount_settled",
            "outstanding",
            "reference",
            "notes",
            "status",
            "cancelled_at",
            "cancel_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_outstanding(self, obj: RetentionRelease) -> str:
        if obj.status != "RELEASED":
            return "0.00"
        return f"{obj.amount - obj.amount_settled:.2f}"


class RetentionReleaseDetailSerializer(RetentionReleaseSerializer):
    allocations = serializers.SerializerMethodField()

    class Meta(RetentionReleaseSerializer.Meta):
        fields = (*RetentionReleaseSerializer.Meta.fields, "allocations")
        read_only_fields = fields

    def get_allocations(self, obj: RetentionRelease) -> list[dict[str, Any]]:
        rows = Allocation.objects.filter(retention_release_id=obj.pk).order_by("created_at")
        return list(AllocationOutSerializer(rows, many=True).data)


class RetentionBookSerializer(serializers.Serializer[Any]):
    deducted = MoneyField(help_text="Retention deducted on issued bills of this book.")
    released = MoneyField(help_text="Released (not cancelled).")
    available = MoneyField(help_text="Still held: can be released.")


class ProjectRetentionSerializer(serializers.Serializer[Any]):
    project_id = serializers.UUIDField()
    GST = RetentionBookSerializer()
    NON_GST = RetentionBookSerializer()
