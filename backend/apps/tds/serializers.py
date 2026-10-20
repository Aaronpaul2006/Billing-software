import re
from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField

from .models import CERTIFICATE_NUMBER_RE, SECTION_RE, TAN_RE, TdsCertificate


class TdsCertificateWriteSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField(help_text="The client who deducted the TDS.")
    deductor_tan = serializers.CharField(help_text="The client's TAN, e.g. BLRS12345E.")
    section = serializers.RegexField(SECTION_RE, default="194C")
    fy_start_year = serializers.IntegerField(
        min_value=2000, max_value=2100, help_text="2026 = FY 2026-27."
    )
    quarter = serializers.IntegerField(
        min_value=1, max_value=4, help_text="1 = Apr-Jun ... 4 = Jan-Mar."
    )
    certificate_number = serializers.RegexField(CERTIFICATE_NUMBER_RE)
    certificate_date = serializers.DateField(required=False, allow_null=True)
    amount_credited = MoneyField(
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
        help_text="As the certificate states.",
    )
    tds_amount = MoneyField(min_value=Decimal("0"))
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)

    def validate_deductor_tan(self, value: str) -> str:
        tan = value.strip().upper()
        if not re.fullmatch(TAN_RE, tan):
            raise serializers.ValidationError(
                "Not a valid TAN (e.g. BLRS12345E).", code="invalid_tan"
            )
        return tan


class TdsCertificateSerializer(serializers.ModelSerializer[TdsCertificate]):
    party_id = serializers.UUIDField()
    party_name = serializers.CharField(source="party.display_name", read_only=True)
    amount_credited = MoneyField(allow_null=True)
    tds_amount = MoneyField()

    class Meta:
        model = TdsCertificate
        fields = (
            "id",
            "version",
            "party_id",
            "party_name",
            "deductor_tan",
            "section",
            "fy_start_year",
            "quarter",
            "certificate_number",
            "certificate_date",
            "amount_credited",
            "tds_amount",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
