"""Serializers shared by several apps."""

from typing import Any

from rest_framework import serializers

from .india import STATE_CODES, is_valid_pincode

STATE_CHOICES = sorted(STATE_CODES)


class AddressSerializer(serializers.Serializer[Any]):
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state_code = serializers.ChoiceField(choices=STATE_CHOICES)
    pincode = serializers.CharField(max_length=6)

    def validate_pincode(self, value: str) -> str:
        if not is_valid_pincode(value):
            raise serializers.ValidationError("A PIN code has 6 digits.", code="invalid_pincode")
        return value


class AddressOutSerializer(AddressSerializer):
    """For responses: a stored address with missing keys (seeded or imported
    data) is shown as it is instead of failing the whole response."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
