from typing import Any

from rest_framework import serializers

from apps.core.india import STATE_CODES, gstin_problem, is_valid_pan, is_valid_pincode
from apps.core.serializers import STATE_CHOICES

from .models import Party

NEEDS_GSTIN = frozenset({"REGISTERED", "COMPOSITION", "SEZ"})
NO_GSTIN = frozenset({"UNREGISTERED", "CONSUMER", "OVERSEAS"})


class PartyAddressSerializer(serializers.Serializer[Any]):
    """Billing address. Indian addresses need a state and PIN; overseas ones
    give a country instead."""

    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    state_code = serializers.ChoiceField(choices=STATE_CHOICES, required=False)
    pincode = serializers.CharField(max_length=10, required=False, allow_blank=True)
    country = serializers.CharField(max_length=2, default="IN")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["country"].upper() == "IN":
            if not attrs.get("state_code"):
                raise serializers.ValidationError({"state_code": "Required."}, code="required")
            if not is_valid_pincode(attrs.get("pincode") or ""):
                raise serializers.ValidationError(
                    {"pincode": "A PIN code has 6 digits."}, code="invalid_pincode"
                )
        return {**attrs, "country": attrs["country"].upper()}


class PartySerializer(serializers.ModelSerializer[Party]):
    billing_address = serializers.JSONField(allow_null=True)
    state_name = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = (
            "id",
            "display_name",
            "legal_name",
            "is_customer",
            "is_vendor",
            "gst_treatment",
            "gstin",
            "pan",
            "state_code",
            "state_name",
            "billing_address",
            "email",
            "phone",
            "is_active",
            "version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_state_name(self, obj: Party) -> str | None:
        return STATE_CODES.get(obj.state_code) if obj.state_code else None


class PartyWriteSerializer(serializers.Serializer[Any]):
    display_name = serializers.CharField(min_length=1, max_length=200)
    legal_name = serializers.CharField(max_length=200, required=False, allow_null=True)
    is_customer = serializers.BooleanField(default=True)
    is_vendor = serializers.BooleanField(default=False)
    gst_treatment = serializers.ChoiceField(choices=Party.GstTreatment.values)
    gstin = serializers.CharField(max_length=15, required=False, allow_null=True)
    pan = serializers.CharField(max_length=10, required=False, allow_null=True)
    state_code = serializers.ChoiceField(choices=STATE_CHOICES, required=False, allow_null=True)
    billing_address = PartyAddressSerializer(required=False, allow_null=True)
    email = serializers.EmailField(max_length=254, required=False, allow_null=True)
    phone = serializers.RegexField(r"^\+?[0-9]{10,15}$", required=False, allow_null=True)
    is_active = serializers.BooleanField(default=True)

    def validate_gstin(self, value: str | None) -> str | None:
        value = value.strip().upper() if value else None
        if value and (problem := gstin_problem(value)):
            raise serializers.ValidationError(problem, code="invalid_gstin")
        return value

    def validate_pan(self, value: str | None) -> str | None:
        value = value.strip().upper() if value else None
        if value and not is_valid_pan(value):
            raise serializers.ValidationError("Not a valid PAN.", code="invalid_pan")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Rules on the result: on PATCH, stored values plus the changes."""
        instance: Party | None = self.context.get("instance")
        current = (
            {
                f: getattr(instance, f)
                for f in ("gst_treatment", "gstin", "pan", "state_code", "is_customer", "is_vendor")
            }
            if instance
            else {}
        )
        merged = {**current, **attrs}
        treatment, gstin = merged.get("gst_treatment"), merged.get("gstin")

        if treatment in NEEDS_GSTIN and not gstin:
            raise serializers.ValidationError(
                {"gstin": f"A {treatment} party needs its GSTIN."}, code="required"
            )
        if treatment in NO_GSTIN and gstin:
            raise serializers.ValidationError(
                {"gstin": f"A {treatment} party has no GSTIN."}, code="gstin_not_allowed"
            )
        if gstin:
            pan = merged.get("pan")
            if pan and pan != gstin[2:12]:
                raise serializers.ValidationError(
                    {"pan": "Does not match the PAN inside the GSTIN."}, code="pan_mismatch"
                )
            if attrs.get("state_code") not in (None, gstin[:2]):
                raise serializers.ValidationError(
                    {"state_code": "Must match the first two digits of the GSTIN."},
                    code="state_mismatch",
                )
            attrs = {**attrs, "pan": gstin[2:12], "state_code": gstin[:2]}
        if not (merged.get("is_customer") or merged.get("is_vendor")):
            raise serializers.ValidationError(
                {"is_customer": "A party is a customer, a vendor, or both."},
                code="no_role",
            )
        return attrs
