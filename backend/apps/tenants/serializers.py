import re
from typing import Any
from zoneinfo import available_timezones

from rest_framework import serializers

from apps.core.india import STATE_CODES, gstin_problem, is_valid_pan
from apps.core.serializers import STATE_CHOICES, AddressOutSerializer, AddressSerializer

from .models import (
    BANK_ACCOUNT_RE,
    IFSC_RE,
    UPI_RE,
    DocType,
    DocumentSeries,
    GstRegistration,
    PrintLayout,
    PrintSettings,
    TallySettings,
    Tenant,
)


def _upper(value: str | None) -> str | None:
    return value.strip().upper() if isinstance(value, str) else value


# --- business profile ---------------------------------------------------------------


class TenantSerializer(serializers.ModelSerializer[Tenant]):
    class Meta:
        model = Tenant
        fields = (
            "id",
            "legal_name",
            "trade_name",
            "pan",
            "status",
            "plan",
            "timezone",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TenantUpdateSerializer(serializers.Serializer[Any]):
    legal_name = serializers.CharField(min_length=1, max_length=200)
    trade_name = serializers.CharField(max_length=200, allow_null=True, allow_blank=False)
    pan = serializers.CharField(max_length=10, allow_null=True)
    timezone = serializers.ChoiceField(choices=sorted(available_timezones()))

    def validate_pan(self, value: str | None) -> str | None:
        value = _upper(value)
        if value is not None and not is_valid_pan(value):
            raise serializers.ValidationError("Not a valid PAN.", code="invalid_pan")
        return value


# --- GST registrations ---------------------------------------------------------------


class GstRegistrationSerializer(serializers.ModelSerializer[GstRegistration]):
    state_name = serializers.SerializerMethodField()
    address = AddressOutSerializer()

    class Meta:
        model = GstRegistration
        fields = (
            "id",
            "registration_type",
            "gstin",
            "state_code",
            "state_name",
            "legal_name",
            "trade_name",
            "address",
            "is_default",
            "is_active",
            "lut_arn",
            "lut_fy_start_year",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_state_name(self, obj: GstRegistration) -> str:
        return STATE_CODES.get(obj.state_code, "")


class GstRegistrationCreateSerializer(serializers.Serializer[Any]):
    registration_type = serializers.ChoiceField(choices=GstRegistration.RegistrationType.values)
    gstin = serializers.CharField(max_length=15, required=False, allow_null=True)
    state_code = serializers.ChoiceField(choices=STATE_CHOICES, required=False)
    legal_name = serializers.CharField(min_length=1, max_length=200)
    trade_name = serializers.CharField(max_length=200, required=False, allow_null=True)
    address = AddressSerializer()
    is_default = serializers.BooleanField(default=False)

    def validate_gstin(self, value: str | None) -> str | None:
        value = _upper(value)
        if value:
            problem = gstin_problem(value)
            if problem:
                raise serializers.ValidationError(problem, code="invalid_gstin")
        return value or None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        gstin, kind = attrs.get("gstin"), attrs["registration_type"]
        if kind == "UNREGISTERED" and gstin:
            raise serializers.ValidationError(
                {"gstin": "An unregistered business has no GSTIN."}, code="gstin_not_allowed"
            )
        if kind != "UNREGISTERED" and not gstin:
            raise serializers.ValidationError(
                {"gstin": f"A {kind} registration needs its GSTIN."}, code="required"
            )
        state = gstin[:2] if gstin else attrs.get("state_code")
        if state is None:
            raise serializers.ValidationError({"state_code": "Required."}, code="required")
        if attrs.get("state_code") not in (None, state):
            raise serializers.ValidationError(
                {"state_code": "Must match the first two digits of the GSTIN."},
                code="state_mismatch",
            )
        if attrs["address"]["state_code"] != state:
            raise serializers.ValidationError(
                {"address": {"state_code": "The address must be in the registration's state."}},
                code="state_mismatch",
            )
        return {**attrs, "gstin": gstin, "state_code": state}


class GstRegistrationUpdateSerializer(serializers.Serializer[Any]):
    """GSTIN, type and state are fixed: register again for a change."""

    legal_name = serializers.CharField(min_length=1, max_length=200)
    trade_name = serializers.CharField(max_length=200, allow_null=True)
    address = AddressSerializer()
    is_default = serializers.BooleanField()
    is_active = serializers.BooleanField()
    lut_arn = serializers.RegexField(
        r"^[A-Z0-9]{15}$",
        allow_null=True,
        help_text="ARN of the Letter of Undertaking (GST RFD-11): zero-rated supplies to SEZs"
        " and exports without IGST. Set together with lut_fy_start_year; null both to remove.",
        error_messages={"invalid": "The ARN is 15 letters and digits."},
    )
    lut_fy_start_year = serializers.IntegerField(
        min_value=2017,
        max_value=2100,
        allow_null=True,
        help_text="The financial year the LUT covers, by its first year (2026 = 2026-27).",
    )

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("lut_arn"), str):
            data = {**data, "lut_arn": data["lut_arn"].replace(" ", "").upper() or None}
        return super().to_internal_value(data)

    def validate_address(self, value: dict[str, Any]) -> dict[str, Any]:
        registration: GstRegistration = self.context["instance"]
        if value["state_code"] != registration.state_code:
            raise serializers.ValidationError(
                {"state_code": "The address must be in the registration's state."},
                code="state_mismatch",
            )
        return value


# --- number series -------------------------------------------------------------------


class DocumentSeriesSerializer(serializers.ModelSerializer[DocumentSeries]):
    gst_registration_id = serializers.UUIDField()
    next_doc_number = serializers.SerializerMethodField(
        help_text="The number the next issued document will get."
    )

    class Meta:
        model = DocumentSeries
        fields = (
            "id",
            "gst_registration_id",
            "doc_type",
            "fy_start_year",
            "prefix",
            "next_number",
            "pad_width",
            "next_doc_number",
            "is_active",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_next_doc_number(self, obj: DocumentSeries) -> str:
        return f"{obj.prefix}{obj.next_number:0{obj.pad_width}d}"


class DocumentSeriesCreateSerializer(serializers.Serializer[Any]):
    gst_registration_id = serializers.UUIDField()
    doc_type = serializers.ChoiceField(choices=DocType.values)
    fy_start_year = serializers.IntegerField(
        min_value=2000, max_value=2100, help_text="2026 for April 2026 to March 2027."
    )
    prefix = serializers.RegexField(
        r"^[A-Za-z0-9/-]{0,10}$", max_length=10, allow_blank=True, default=""
    )
    next_number = serializers.IntegerField(min_value=1, default=1)
    pad_width = serializers.IntegerField(min_value=1, max_value=8, default=4)
    is_active = serializers.BooleanField(default=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if len(attrs["prefix"]) + attrs["pad_width"] > 16:
            raise serializers.ValidationError(
                {"prefix": "Prefix plus digits may be at most 16 characters (GST rule)."},
                code="too_long",
            )
        return attrs


class DocumentSeriesUpdateSerializer(serializers.Serializer[Any]):
    """Registration, type and year are fixed; the rest is locked once used."""

    prefix = serializers.RegexField(r"^[A-Za-z0-9/-]{0,10}$", max_length=10, allow_blank=True)
    next_number = serializers.IntegerField(min_value=1)
    pad_width = serializers.IntegerField(min_value=1, max_value=8)
    is_active = serializers.BooleanField()


class SetupStatusSerializer(serializers.Serializer[Any]):
    """Setting up a new business (H.2): each step done or not."""

    gst_registration = serializers.BooleanField(help_text="A GSTIN (or the unregistered profile).")
    number_series = serializers.BooleanField(help_text="An active number series.")
    client = serializers.BooleanField()
    project = serializers.BooleanField()
    first_bill = serializers.BooleanField(help_text="Something issued (not a draft).")
    team = serializers.BooleanField(help_text="Someone besides the first member, or invited.")
    complete = serializers.BooleanField()


# --- print settings (B.12) ------------------------------------------------------------


class PrintSettingsSerializer(serializers.ModelSerializer[PrintSettings]):
    class Meta:
        model = PrintSettings
        fields = (
            "layout",
            "logo_attachment_id",
            "signature_attachment_id",
            "bank_account_name",
            "bank_name",
            "bank_account_number",
            "bank_ifsc",
            "bank_branch",
            "upi_id",
            "default_terms",
            "version",
        )
        read_only_fields = fields


def _text(value: str | None) -> str | None:
    """Blank means not set."""
    if value is None:
        return None
    value = value.strip()
    return value or None


class PrintSettingsUpdateSerializer(serializers.Serializer[Any]):
    layout = serializers.ChoiceField(choices=PrintLayout.choices)
    logo_attachment_id = serializers.UUIDField(allow_null=True)
    signature_attachment_id = serializers.UUIDField(allow_null=True)
    bank_account_name = serializers.CharField(max_length=200, allow_null=True, allow_blank=True)
    bank_name = serializers.CharField(max_length=200, allow_null=True, allow_blank=True)
    bank_account_number = serializers.CharField(max_length=40, allow_null=True, allow_blank=True)
    bank_ifsc = serializers.CharField(max_length=20, allow_null=True, allow_blank=True)
    bank_branch = serializers.CharField(max_length=200, allow_null=True, allow_blank=True)
    upi_id = serializers.CharField(max_length=130, allow_null=True, allow_blank=True)
    default_terms = serializers.CharField(
        max_length=5000, allow_null=True, allow_blank=True, trim_whitespace=False
    )

    def validate_bank_account_name(self, value: str | None) -> str | None:
        return _text(value)

    def validate_bank_name(self, value: str | None) -> str | None:
        return _text(value)

    def validate_bank_branch(self, value: str | None) -> str | None:
        return _text(value)

    def validate_default_terms(self, value: str | None) -> str | None:
        return _text(value)

    def validate_bank_account_number(self, value: str | None) -> str | None:
        value = _text(value)
        if value is None:
            return None
        value = re.sub(r"[\s-]", "", value)  # people type it in groups
        if not re.match(BANK_ACCOUNT_RE, value):
            raise serializers.ValidationError(
                "An account number is 6 to 18 digits.", code="invalid_account_number"
            )
        return value

    def validate_bank_ifsc(self, value: str | None) -> str | None:
        value = _upper(_text(value))
        if value is not None and not re.match(IFSC_RE, value):
            raise serializers.ValidationError(
                "An IFSC is 11 characters, like SBIN0001234 (the 5th is a zero).",
                code="invalid_ifsc",
            )
        return value

    def validate_upi_id(self, value: str | None) -> str | None:
        value = _text(value)
        if value is not None and not re.match(UPI_RE, value):
            raise serializers.ValidationError(
                "A UPI ID looks like name@bank, e.g. nairconstructions@okaxis.",
                code="invalid_upi_id",
            )
        return value


# --- Tally ledger names (B.16) --------------------------------------------------------


class TallySettingsSerializer(serializers.ModelSerializer[TallySettings]):
    class Meta:
        model = TallySettings
        fields = (
            "sales_ledger",
            "cgst_ledger",
            "sgst_ledger",
            "igst_ledger",
            "cess_ledger",
            "round_off_ledger",
            "tds_ledger",
            "gst_tds_ledger",
            "retention_ledger",
            "advance_ledger",
            "bank_ledger",
            "cash_ledger",
            "version",
        )
        read_only_fields = fields


def _ledger_name() -> serializers.CharField:
    return serializers.CharField(min_length=1, max_length=200)


class TallySettingsUpdateSerializer(serializers.Serializer[Any]):
    """Ledger names exactly as they are in Tally (Tally matches them by name)."""

    sales_ledger = _ledger_name()
    cgst_ledger = _ledger_name()
    sgst_ledger = _ledger_name()
    igst_ledger = _ledger_name()
    cess_ledger = _ledger_name()
    round_off_ledger = _ledger_name()
    tds_ledger = _ledger_name()
    gst_tds_ledger = _ledger_name()
    retention_ledger = _ledger_name()
    advance_ledger = _ledger_name()
    bank_ledger = _ledger_name()
    cash_ledger = _ledger_name()
