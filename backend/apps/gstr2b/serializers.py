from typing import Any

from rest_framework import serializers

from apps.core.fields import MoneyField

from .models import Gstr2bReturn

STATUSES = ["MATCHED", "AMOUNTS_DIFFER", "NOT_IN_BOOKS", "NOT_IN_2B"]


class UploadSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(
        help_text="GSTR-2B as downloaded from the GST portal (JSON or Excel), at most 20 MB"
    )


class Gstr2bReturnSerializer(serializers.ModelSerializer[Gstr2bReturn]):
    gst_registration_id = serializers.UUIDField()
    gstin = serializers.CharField(source="gst_registration.gstin", read_only=True)
    uploaded_by = serializers.CharField(source="created_by.full_name", read_only=True)

    class Meta:
        model = Gstr2bReturn
        fields = (
            "id",
            "gst_registration_id",
            "gstin",
            "period",
            "generated_on",
            "file_name",
            "doc_count",
            "uploaded_by",
            "created_at",
        )
        read_only_fields = fields


class PortalDocSerializer(serializers.Serializer[Any]):
    """A document as the GSTR-2B shows it."""

    id = serializers.UUIDField()
    section = serializers.CharField()
    doc_type = serializers.ChoiceField(choices=["INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"])
    doc_number = serializers.CharField()
    original_number = serializers.CharField(allow_null=True)
    doc_date = serializers.DateField()
    taxable_value = MoneyField()
    tax = MoneyField()
    itc_available = serializers.BooleanField()
    itc_reason = serializers.CharField(allow_null=True)
    reverse_charge = serializers.BooleanField()


class BookDocSerializer(serializers.Serializer[Any]):
    """A document in our books."""

    kind = serializers.ChoiceField(choices=["VENDOR_BILL", "EXPENSE"])
    id = serializers.UUIDField()
    number = serializers.CharField()
    doc_date = serializers.DateField()
    taxable_value = MoneyField()
    tax = MoneyField()
    itc_eligible = serializers.BooleanField()


class ReconRowSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=STATUSES)
    supplier_gstin = serializers.CharField()
    supplier_name = serializers.CharField()
    portal = PortalDocSerializer(allow_null=True, help_text="As in the GSTR-2B")
    books = BookDocSerializer(allow_null=True, help_text="As in our books")
    taxable_difference = MoneyField(help_text="2B less books")
    tax_difference = MoneyField(help_text="2B less books")
    note = serializers.CharField()


class ReconSummarySerializer(serializers.Serializer[Any]):
    matched = serializers.IntegerField()
    amounts_differ = serializers.IntegerField()
    not_in_books = serializers.IntegerField()
    not_in_2b = serializers.IntegerField()
    itc_in_2b = MoneyField(help_text="Available ITC the portal shows, credit notes taken off")
    itc_matched = MoneyField()
    itc_not_in_books = MoneyField(help_text="In the 2B but not in our books: record the bills")
    itc_at_risk = MoneyField(help_text="Claimed in our books, not in the 2B: ask the supplier")


class ReconciliationSerializer(serializers.Serializer[Any]):
    gst_return = Gstr2bReturnSerializer(source="return_")
    summary = ReconSummarySerializer()
    rows = ReconRowSerializer(many=True)


class ReconQuerySerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=STATUSES, required=False)
