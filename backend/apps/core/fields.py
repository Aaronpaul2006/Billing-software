"""Serializer fields for money and quantities (docs/02-api-design.md §1).

Money, quantities and rates travel as JSON *strings* ("11800.00"): a JSON
number becomes a binary float in JavaScript/Dart and corrupts amounts, so a
number is rejected outright rather than converted.
"""

from decimal import Decimal
from typing import Any, ClassVar

from rest_framework import serializers


class StrictDecimalField(serializers.DecimalField):
    default_error_messages: ClassVar[dict[str, Any]] = {
        **serializers.DecimalField.default_error_messages,
        "not_a_string": 'Send this as a string, e.g. "1180.00", not as a JSON number.',
    }

    def __init__(self, **kwargs: Any) -> None:
        kwargs["coerce_to_string"] = True
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> Decimal:
        if not isinstance(data, str):
            self.fail("not_a_string")
        return super().to_internal_value(data)


class MoneyField(StrictDecimalField):
    """numeric(14,2): rupees and paise."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(**kwargs)


class QuantityField(StrictDecimalField):
    """numeric(14,3): measured quantities (cum, sqm, kg...)."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 3)
        super().__init__(**kwargs)


class PercentField(StrictDecimalField):
    """numeric(5,2) between 0 and 100 (GST rates are further limited to 50)."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 5)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("min_value", Decimal("0"))
        kwargs.setdefault("max_value", Decimal("100"))
        super().__init__(**kwargs)
