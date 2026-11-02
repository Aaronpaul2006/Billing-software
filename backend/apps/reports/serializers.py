from datetime import date, timedelta
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.core.fields import MoneyField

BOOKS = ["ALL", "GST", "NON_GST"]
MAX_RANGE = timedelta(days=366 * 5)


def fy_start(d: date) -> date:
    """1 April of the Indian financial year containing `d`."""
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


class PeriodSerializer(serializers.Serializer[Any]):
    """`from` / `to` (default: this financial year to today) and `book`."""

    from_ = serializers.DateField(required=False, help_text="Default: 1 April of this FY.")
    to = serializers.DateField(required=False, help_text="Default: today.")
    book = serializers.ChoiceField(choices=BOOKS, default="ALL")

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_")  # `from` is a Python keyword
        return fields

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        today = timezone.localdate()
        start, end = attrs.get("from") or fy_start(today), attrs.get("to") or today
        if start > end:
            raise serializers.ValidationError({"from": "After `to`."}, code="invalid_dates")
        if end - start > MAX_RANGE:
            raise serializers.ValidationError({"from": "At most 5 years."}, code="range_too_long")
        return {"start": start, "end": end, "book": attrs["book"]}


class GstPeriodSerializer(serializers.Serializer[Any]):
    period = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", help_text="YYYY-MM")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        year, month = (int(x) for x in attrs["period"].split("-"))
        start = date(year, month, 1)
        end = _month_end(start)
        return {"start": start, "end": end, "period": attrs["period"]}


def _month_end(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The period just before [start, end]: the same number of calendar months
    when it spans whole months (October -> September, Q2 -> Q1), otherwise the
    same number of days."""
    prev_end = start - timedelta(days=1)
    if start.day == 1 and end == _month_end(end):
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        index = start.year * 12 + start.month - 1 - months
        return date(index // 12, index % 12 + 1, 1), prev_end
    return prev_end - (end - start), prev_end


# --- responses (documented in the OpenAPI schema) -------------------------------------


class ReportTotalsSerializer(serializers.Serializer[Any]):
    billed = MoneyField()
    taxable = MoneyField()
    tax = MoneyField()
    collected = MoneyField()
    expenses = MoneyField()
    outstanding = MoneyField(help_text="Now, not for the period.")


class SummarySerializer(serializers.Serializer[Any]):
    book = serializers.CharField()
    period = serializers.DictField(child=serializers.DateField())
    previous_period = serializers.DictField(child=serializers.DateField())
    current = ReportTotalsSerializer()
    previous = ReportTotalsSerializer()


class MonthSerializer(serializers.Serializer[Any]):
    month = serializers.DateField()
    book = serializers.CharField()
    document_count = serializers.IntegerField()
    taxable_value = MoneyField()
    tax = MoneyField()
    billed = MoneyField()


class ReceivableSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    display_name = serializers.CharField()
    document_count = serializers.IntegerField()
    not_due = MoneyField(source="bucket_not_due")
    days_1_30 = MoneyField(source="bucket_1_30")
    days_31_60 = MoneyField(source="bucket_31_60")
    days_61_90 = MoneyField(source="bucket_61_90")
    days_90_plus = MoneyField(source="bucket_90_plus")
    total = MoneyField()


class ProjectReportSerializer(serializers.Serializer[Any]):
    project_id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    contract_value = MoneyField(allow_null=True)
    billed_taxable = MoneyField()
    retention_held = MoneyField(help_text="Deducted on issued bills, less released.")
    retention_released = MoneyField()
    tds_deducted = MoneyField()
    advance_recovered = MoneyField()
    outstanding = MoneyField()
    cost = MoneyField(help_text="Expenses; GST counts unless input tax credit is claimable.")
    margin = MoneyField(help_text="billed_taxable - cost")


class GstRowSerializer(serializers.Serializer[Any]):
    supply = serializers.ChoiceField(
        choices=["B2B", "B2C", "B2B_REVERSE_CHARGE", "SEZ", "EXPORT"],
        help_text="B2B_REVERSE_CHARGE: the recipient pays the tax (not ours to pay).",
    )
    gst_rate = MoneyField()
    document_count = serializers.IntegerField()
    taxable_value = MoneyField()
    cgst = MoneyField()
    sgst = MoneyField()
    igst = MoneyField()
    cess = MoneyField()


# Response envelopes, so the OpenAPI schema matches what the views return.


class MonthsSerializer(serializers.Serializer[Any]):
    results = MonthSerializer(many=True)


class ReceivablesSerializer(serializers.Serializer[Any]):
    results = ReceivableSerializer(many=True)
    totals = ReceivableSerializer(help_text="All parties together.")


class ProjectReportsSerializer(serializers.Serializer[Any]):
    results = ProjectReportSerializer(many=True)


class GstTotalsSerializer(serializers.Serializer[Any]):
    taxable_value = MoneyField()
    cgst = MoneyField()
    sgst = MoneyField()
    igst = MoneyField()
    cess = MoneyField()


class GstSummaryReportSerializer(serializers.Serializer[Any]):
    period = serializers.CharField(help_text="YYYY-MM")
    results = GstRowSerializer(many=True)
    totals = GstTotalsSerializer()


# --- TDS reconciliation (Phase 3.4) ------------------------------------------------------


class TdsParamsSerializer(serializers.Serializer[Any]):
    fy = serializers.IntegerField(
        min_value=2000,
        max_value=2100,
        required=False,
        help_text="2026 = FY 2026-27; default: this FY.",
    )
    party_id = serializers.UUIDField(required=False)


class TdsRowSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    display_name = serializers.CharField()
    quarter = serializers.IntegerField()
    deductor_tans = serializers.CharField(allow_null=True)
    bill_count = serializers.IntegerField()
    taxable_value = MoneyField(help_text="Of the bills with TDS in the quarter.")
    expected = MoneyField(help_text="TDS deducted on our issued bills.")
    certificate_count = serializers.IntegerField()
    certified = MoneyField(help_text="TDS as the Form 16A certificates state.")
    difference = MoneyField(help_text="certified - expected")
    status = serializers.ChoiceField(choices=["MATCHED", "SHORT", "EXCESS", "NOT_RECEIVED"])
    certificate_due = serializers.DateField(help_text="Form 16A is due 15 days after the return.")
    overdue = serializers.BooleanField()


class TdsTotalsSerializer(serializers.Serializer[Any]):
    expected = MoneyField()
    certified = MoneyField()
    difference = MoneyField()


class TdsReconciliationSerializer(serializers.Serializer[Any]):
    fy_start_year = serializers.IntegerField()
    results = TdsRowSerializer(many=True)
    totals = TdsTotalsSerializer()


class StatementEntrySerializer(serializers.Serializer[Any]):
    date = serializers.DateField()
    kind = serializers.ChoiceField(
        choices=[
            "TAX_INVOICE",
            "BILL_OF_SUPPLY",
            "DEBIT_NOTE",
            "CREDIT_NOTE",
            "RETENTION_RELEASE",
            "PAYMENT",
        ]
    )
    reference = serializers.CharField(allow_null=True)
    description = serializers.CharField()
    debit = MoneyField()
    credit = MoneyField()
    balance = MoneyField(help_text="After this entry; positive = the client owes.")
    document_id = serializers.UUIDField(allow_null=True)
    payment_id = serializers.UUIDField(allow_null=True)
    retention_release_id = serializers.UUIDField(allow_null=True)


class StatementPartySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    display_name = serializers.CharField()
    gstin = serializers.CharField(allow_null=True)


class StatementSerializer(serializers.Serializer[Any]):
    party = StatementPartySerializer()
    from_ = serializers.DateField()
    to = serializers.DateField()
    opening_balance = MoneyField(help_text="Positive = the client owes; negative = paid ahead.")
    entries = StatementEntrySerializer(many=True)
    total_debit = MoneyField()
    total_credit = MoneyField()
    closing_balance = MoneyField()

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_")  # `from` is a Python keyword
        return fields


# --- the main dashboard (W.6) ------------------------------------------------------------


class DashboardTotalsSerializer(serializers.Serializer[Any]):
    billed = MoneyField(help_text="Issued in the period, with GST; credit notes subtract.")
    collected = MoneyField(help_text="Payments received in the period.")
    outstanding = MoneyField(help_text="Owed to you today.")
    overdue = MoneyField(help_text="The part of `outstanding` past its due date.")
    expenses = MoneyField(help_text="Recorded in the period, with GST.")
    margin = MoneyField(
        help_text="Billed taxable value less cost (expense GST counts unless ITC is claimable)."
    )


class DashboardMonthSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(help_text="First day of the month.")
    billed = MoneyField()
    collected = MoneyField()


class DashboardOverdueRowSerializer(serializers.Serializer[Any]):
    document_id = serializers.UUIDField()
    doc_type = serializers.CharField()
    doc_number = serializers.CharField()
    party_id = serializers.UUIDField()
    party_name = serializers.CharField()
    due_date = serializers.DateField()
    days_overdue = serializers.IntegerField()
    outstanding = MoneyField()
    party_has_email = serializers.BooleanField(help_text="False: a reminder cannot be emailed.")
    last_reminder_at = serializers.DateTimeField(allow_null=True)


class DashboardOverdueSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField(help_text="All overdue bills; `results` has the 10 oldest.")
    results = DashboardOverdueRowSerializer(many=True)


class DashboardProjectSerializer(serializers.Serializer[Any]):
    project_id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    billed_taxable = MoneyField()
    cost = MoneyField()
    margin = MoneyField()


class DashboardDraftRowSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    doc_type = serializers.CharField()
    doc_date = serializers.DateField()
    party_name = serializers.CharField()
    grand_total = MoneyField()
    updated_at = serializers.DateTimeField()


class DashboardDraftsSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
    results = DashboardDraftRowSerializer(many=True, help_text="The 5 waiting longest.")


class DashboardSerializer(serializers.Serializer[Any]):
    book = serializers.CharField()
    period = serializers.DictField(child=serializers.DateField())
    previous_period = serializers.DictField(child=serializers.DateField())
    totals = DashboardTotalsSerializer()
    previous = DashboardTotalsSerializer(
        help_text="The same figures for the period before (outstanding / overdue: today's)."
    )
    months = DashboardMonthSerializer(many=True, help_text="12 months up to `to`, oldest first.")
    overdue = DashboardOverdueSerializer()
    losing_projects = DashboardProjectSerializer(
        many=True, help_text="Costs so far exceed billing (at most 5, worst first)."
    )
    drafts = DashboardDraftsSerializer()
