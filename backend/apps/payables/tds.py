"""TDS we deduct on vendor bills (Part B): the suggestion for a new bill.

Rates and limits are data (tds_rates.json), not code. The rule (s.194C): TDS
applies once a single bill is over the single-bill limit, or the vendor's bills
in the financial year together pass the year limit. The rate follows the
vendor's PAN: 1 % for an individual or HUF (4th letter P or H), 2 % otherwise,
20 % when we have no PAN (s.206AA). The app suggests; the person decides.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path
from typing import Any

from django.db.models import Sum

from apps.core.india import fy_start_year
from apps.parties.models import Party

from .models import VendorBill


@cache
def rates() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((Path(__file__).parent / "tds_rates.json").read_text("utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def tds_amount(taxable_value: Decimal, rate: Decimal) -> Decimal:
    """TDS on the value before GST, rounded to the rupee (s.288B)."""
    return (
        (taxable_value * rate / 100)
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        .quantize(Decimal("0.01"))
    )


@dataclass(frozen=True)
class Suggestion:
    section: str | None
    rate: Decimal
    amount: Decimal
    reason: str
    year_total: Decimal  # this vendor's bills in the financial year, before this one


def _year_total(vendor_id: uuid.UUID, bill_date: date, exclude: uuid.UUID | None) -> Decimal:
    fy = fy_start_year(bill_date)
    rows = VendorBill.objects.filter(
        vendor_party_id=vendor_id,
        status="RECORDED",
        bill_date__gte=date(fy, 4, 1),
        bill_date__lt=date(fy + 1, 4, 1),
    )
    if exclude:
        rows = rows.exclude(pk=exclude)
    total: Decimal | None = rows.aggregate(t=Sum("taxable_value"))["t"]
    return total or Decimal("0.00")


def suggest(
    vendor: Party,
    category: str,
    taxable_value: Decimal,
    bill_date: date,
    exclude: uuid.UUID | None = None,
) -> Suggestion:
    year = _year_total(vendor.pk, bill_date, exclude)
    for section, rule in rates().items():
        if category not in rule["categories"]:
            continue
        single, yearly = Decimal(rule["single_bill_limit"]), Decimal(rule["year_limit"])
        if taxable_value <= single and year + taxable_value <= yearly:
            return Suggestion(
                None,
                Decimal("0.00"),
                Decimal("0.00"),
                f"Below the {section} limits: ₹{single:,.0f} a bill and ₹{yearly:,.0f} a year"
                f" ({year + taxable_value:,.2f} so far this year).",
                year,
            )
        pan = vendor.pan or ""
        if not pan:
            rate = Decimal(rule["rate_without_pan"])
            why = "the vendor's PAN is not saved, so the higher rate applies"
        elif pan[3:4] in ("P", "H"):
            rate = Decimal(rule["rate_individual_or_huf"])
            why = "the vendor is an individual or HUF (from the PAN)"
        else:
            rate = Decimal(rule["rate_other"])
            why = "the vendor is a firm or company (from the PAN)"
        return Suggestion(
            section,
            rate,
            tds_amount(taxable_value, rate),
            f"{section} ({rule['title'].lower()}): {rate.normalize()} %, because {why}.",
            year,
        )
    return Suggestion(
        None,
        Decimal("0.00"),
        Decimal("0.00"),
        "TDS does not usually apply to this kind of bill.",
        year,
    )
