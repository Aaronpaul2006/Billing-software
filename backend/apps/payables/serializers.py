from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.expenses.models import ExpenseCategory
from apps.payments.models import PaymentMode

from .models import VendorAllocation, VendorBill, VendorPayment

PAISA = Decimal("0.01")
SECTION = r"^19[0-9]{1,2}[A-Z]{0,3}$"


class VendorBillWriteSerializer(serializers.Serializer[Any]):
    vendor_party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    bill_number = serializers.CharField(max_length=50, help_text="The vendor's own number")
    bill_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    category = serializers.ChoiceField(choices=ExpenseCategory.choices)
    description = serializers.CharField(max_length=1000)
    taxable_value = MoneyField(min_value=Decimal("0.00"), help_text="Before GST")
    gst_amount = MoneyField(min_value=Decimal("0.00"), required=False)
    itc_eligible = serializers.BooleanField(required=False)
    tds_section = serializers.RegexField(
        SECTION, required=False, allow_null=True, help_text="e.g. 194C; empty for no TDS"
    )
    tds_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("30"),
        required=False,
        allow_null=True,
        coerce_to_string=True,
        help_text="Percent of the value before GST; the TDS amount is worked out (to the rupee)",
    )
    attachment_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)


class VendorBillSerializer(serializers.ModelSerializer[VendorBill]):
    vendor_party_id = serializers.UUIDField()
    vendor_name = serializers.CharField(source="vendor_party.display_name", read_only=True)
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    taxable_value = MoneyField()
    gst_amount = MoneyField()
    total_amount = MoneyField()
    tds_rate = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    tds_amount = MoneyField()
    net_payable = MoneyField(help_text="Total less the TDS we deduct: what we pay the vendor")
    amount_paid = MoneyField()
    outstanding = serializers.SerializerMethodField()
    attachment_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = VendorBill
        fields = (
            "id",
            "version",
            "vendor_party_id",
            "vendor_name",
            "project_id",
            "project_name",
            "bill_number",
            "bill_date",
            "due_date",
            "category",
            "description",
            "taxable_value",
            "gst_amount",
            "total_amount",
            "itc_eligible",
            "tds_section",
            "tds_rate",
            "tds_amount",
            "net_payable",
            "amount_paid",
            "outstanding",
            "attachment_id",
            "notes",
            "status",
            "voided_at",
            "void_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_outstanding(self, obj: VendorBill) -> str:
        if obj.status != "RECORDED":
            return "0.00"
        return f"{obj.net_payable - obj.amount_paid:.2f}"


class VendorAllocationInSerializer(serializers.Serializer[Any]):
    vendor_bill_id = serializers.UUIDField()
    amount = MoneyField(min_value=PAISA)


class VendorPaymentCreateSerializer(serializers.Serializer[Any]):
    vendor_party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    payment_date = serializers.DateField()
    amount = MoneyField(min_value=PAISA)
    mode = serializers.ChoiceField(choices=PaymentMode.choices)
    reference = serializers.CharField(
        max_length=100, required=False, allow_null=True, help_text="UTR / cheque number"
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)
    allocations = VendorAllocationInSerializer(many=True, required=False)


class VendorAllocationOutSerializer(serializers.ModelSerializer[VendorAllocation]):
    vendor_bill_id = serializers.UUIDField()
    bill_number = serializers.CharField(source="vendor_bill.bill_number", read_only=True)
    amount = MoneyField()

    class Meta:
        model = VendorAllocation
        fields = ("id", "vendor_bill_id", "bill_number", "amount", "created_at")
        read_only_fields = fields


class VendorPaymentSerializer(serializers.ModelSerializer[VendorPayment]):
    vendor_party_id = serializers.UUIDField()
    vendor_name = serializers.CharField(source="vendor_party.display_name", read_only=True)
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    amount = MoneyField()
    unallocated = serializers.SerializerMethodField()
    allocations = serializers.SerializerMethodField()

    class Meta:
        model = VendorPayment
        fields = (
            "id",
            "version",
            "vendor_party_id",
            "vendor_name",
            "project_id",
            "project_name",
            "payment_date",
            "amount",
            "mode",
            "reference",
            "notes",
            "status",
            "unallocated",
            "allocations",
            "voided_at",
            "void_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def _allocations(self, obj: VendorPayment) -> list[VendorAllocation]:
        return list(obj.allocations.all())

    def get_unallocated(self, obj: VendorPayment) -> str:
        if obj.status != "RECORDED":
            return "0.00"
        used = sum((a.amount for a in self._allocations(obj)), Decimal("0.00"))
        return f"{obj.amount - used:.2f}"

    @extend_schema_field(VendorAllocationOutSerializer(many=True))
    def get_allocations(self, obj: VendorPayment) -> list[dict[str, Any]]:
        return list(VendorAllocationOutSerializer(self._allocations(obj), many=True).data)


class TdsQuerySerializer(serializers.Serializer[Any]):
    vendor_party_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=ExpenseCategory.choices)
    taxable_value = MoneyField(min_value=Decimal("0.00"))
    bill_date = serializers.DateField()
    vendor_bill_id = serializers.UUIDField(
        required=False, help_text="When editing: leave this bill out of the year's total"
    )


class TdsSuggestionSerializer(serializers.Serializer[Any]):
    section = serializers.CharField(allow_null=True, help_text="Null: no TDS suggested")
    rate = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    amount = MoneyField()
    reason = serializers.CharField(help_text="Why, in words")
    year_total = MoneyField(help_text="The vendor's bills this financial year, before this one")


class PayableSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    display_name = serializers.CharField()
    bill_count = serializers.IntegerField()
    not_due = MoneyField()
    days_1_30 = MoneyField()
    days_31_60 = MoneyField()
    days_61_90 = MoneyField()
    days_90_plus = MoneyField()
    total = MoneyField()


class PayablesSerializer(serializers.Serializer[Any]):
    as_of = serializers.DateField()
    results = PayableSerializer(many=True)
    totals = PayableSerializer()
