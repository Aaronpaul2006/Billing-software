from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.documents.models import Document

from .models import Allocation, Payment, PaymentMode
from .services import allocated_total

PAISA = Decimal("0.01")


class AllocationInSerializer(serializers.Serializer[Any]):
    document_id = serializers.UUIDField()
    amount = MoneyField(min_value=PAISA)


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
    document_id = serializers.UUIDField()
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
            "payment_id",
            "credit_note_id",
            "amount",
            "created_at",
        )
        read_only_fields = fields

    def get_doc_number(self, obj: Allocation) -> str | None:
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
