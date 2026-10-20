from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.payments.models import PaymentMode

from .models import Expense, ExpenseCategory

ZERO = Decimal("0")


class ExpenseSerializer(serializers.ModelSerializer[Expense]):
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    vendor_party_id = serializers.UUIDField(allow_null=True)
    vendor_name = serializers.CharField(
        source="vendor_party.display_name", allow_null=True, read_only=True
    )
    attachment_id = serializers.UUIDField(allow_null=True)
    taxable_value = MoneyField()
    gst_amount = MoneyField()
    total_amount = MoneyField()
    amount_paid = MoneyField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = (
            "id",
            "version",
            "project_id",
            "project_name",
            "vendor_party_id",
            "vendor_name",
            "category",
            "expense_date",
            "description",
            "vendor_bill_number",
            "taxable_value",
            "gst_amount",
            "total_amount",
            "itc_eligible",
            "amount_paid",
            "balance",
            "payment_mode",
            "attachment_id",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_balance(self, obj: Expense) -> str:
        return f"{obj.total_amount - obj.amount_paid:.2f}"


class ExpenseWriteSerializer(serializers.Serializer[Any]):
    """The total is computed by the server: taxable value + GST."""

    project_id = serializers.UUIDField(required=False, allow_null=True)
    vendor_party_id = serializers.UUIDField(required=False, allow_null=True)
    category = serializers.ChoiceField(choices=ExpenseCategory.values)
    expense_date = serializers.DateField()
    description = serializers.CharField(min_length=1, max_length=1000)
    vendor_bill_number = serializers.CharField(max_length=50, required=False, allow_null=True)
    taxable_value = MoneyField(min_value=ZERO)
    gst_amount = MoneyField(min_value=ZERO, required=False)
    itc_eligible = serializers.BooleanField(required=False)
    amount_paid = MoneyField(min_value=ZERO, required=False)
    payment_mode = serializers.ChoiceField(
        choices=PaymentMode.choices, required=False, allow_null=True
    )
    attachment_id = serializers.UUIDField(required=False, allow_null=True)
