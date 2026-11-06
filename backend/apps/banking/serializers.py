from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.payables.serializers import VendorAllocationInSerializer
from apps.payments.serializers import AllocationInSerializer

from . import services
from .models import BankLine


class StatementUploadSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(help_text="The bank's statement: CSV or .xlsx, at most 5 MB.")
    account_label = serializers.CharField(
        max_length=60, required=False, help_text="Import: which account, e.g. HDFC current 1234"
    )
    mapping = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="JSON {field: header as in the file} for date, narration, reference, "
        "money_in, money_out, amount, dr_cr, balance; when the columns are not found",
    )


class StatementLineSerializer(serializers.Serializer[Any]):
    row = serializers.IntegerField()
    line_date = serializers.DateField()
    narration = serializers.CharField()
    reference = serializers.CharField(allow_null=True)
    money_in = MoneyField()
    money_out = MoneyField()
    balance = MoneyField(allow_null=True)


class StatementPreviewSerializer(serializers.Serializer[Any]):
    ready = serializers.BooleanField(help_text="False: choose the columns (headers lists them)")
    headers = serializers.ListField(child=serializers.CharField())
    columns = serializers.DictField(child=serializers.CharField(), help_text="field -> header")
    line_count = serializers.IntegerField()
    skipped_rows = serializers.ListField(child=serializers.IntegerField())
    lines = StatementLineSerializer(many=True, help_text="The first 20")


class StatementImportedSerializer(serializers.Serializer[Any]):
    added = serializers.IntegerField()
    duplicates = serializers.IntegerField(help_text="Lines imported before: skipped")
    skipped_rows = serializers.ListField(child=serializers.IntegerField())
    line_count = serializers.IntegerField()


class SuggestionSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=["payment", "vendor_payment", "bill", "vendor_bill"])
    id = serializers.UUIDField()
    party_id = serializers.UUIDField()
    party_name = serializers.CharField()
    title = serializers.CharField(help_text='In words: "Bill INV/0002"')
    score = serializers.IntegerField()


class BankLineSerializer(serializers.ModelSerializer[BankLine]):
    money_in = MoneyField()
    money_out = MoneyField()
    balance = MoneyField(allow_null=True)
    payment_id = serializers.UUIDField(allow_null=True)
    vendor_payment_id = serializers.UUIDField(allow_null=True)
    suggestions = serializers.SerializerMethodField()

    class Meta:
        model = BankLine
        fields = (
            "id",
            "version",
            "account_label",
            "line_date",
            "narration",
            "reference",
            "money_in",
            "money_out",
            "balance",
            "status",
            "payment_id",
            "vendor_payment_id",
            "note",
            "suggestions",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(SuggestionSerializer(many=True))
    def get_suggestions(self, obj: BankLine) -> list[dict[str, Any]]:
        return list(SuggestionSerializer(services.suggestions(obj), many=True).data)


class BankAccountsSerializer(serializers.Serializer[Any]):
    results = serializers.ListField(child=serializers.CharField())


class MatchSerializer(serializers.Serializer[Any]):
    payment_id = serializers.UUIDField(required=False, help_text="Money in: the payment it is")
    vendor_payment_id = serializers.UUIDField(
        required=False, help_text="Money out: the payment to a vendor it is"
    )


class RecordFromLineSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField(required=False, help_text="Money in: who paid")
    vendor_party_id = serializers.UUIDField(required=False, help_text="Money out: who was paid")
    project_id = serializers.UUIDField(required=False, allow_null=True)
    allocations = AllocationInSerializer(many=True, required=False)
    vendor_allocations = VendorAllocationInSerializer(many=True, required=False)


class IgnoreSerializer(serializers.Serializer[Any]):
    note = serializers.CharField(
        max_length=200, required=False, allow_null=True, help_text="e.g. bank charges"
    )
