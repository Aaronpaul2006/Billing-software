from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.fields import MoneyField
from apps.expenses.models import ExpenseCategory
from apps.payments.models import PaymentMode

from .models import (
    VendorAllocation,
    VendorBill,
    VendorBillLine,
    VendorPayment,
    VendorRetentionRelease,
    WorkOrder,
    WorkOrderItem,
)

PAISA = Decimal("0.01")
SECTION = r"^19[0-9]{1,2}[A-Z]{0,3}$"


class VendorBillWriteSerializer(serializers.Serializer[Any]):
    vendor_party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    bill_number = serializers.CharField(max_length=50, help_text="The vendor's own number")
    bill_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    category = serializers.ChoiceField(choices=ExpenseCategory.choices)
    description = serializers.CharField(max_length=1000)
    taxable_value = MoneyField(min_value=Decimal("0.00"), help_text="Before GST")
    gst_amount = MoneyField(min_value=Decimal("0.00"), required=False)
    itc_eligible = serializers.BooleanField(required=False)
    tds_section = serializers.RegexField(
        SECTION, required=False, allow_null=True, help_text="e.g. 194C; empty for no TDS"
    )
    tds_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("30"),
        required=False,
        allow_null=True,
        coerce_to_string=True,
        help_text="Percent of the value before GST; the TDS amount is worked out (to the rupee)",
    )
    attachment_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)


class VendorBillSerializer(serializers.ModelSerializer[VendorBill]):
    vendor_party_id = serializers.UUIDField()
    vendor_name = serializers.CharField(source="vendor_party.display_name", read_only=True)
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    taxable_value = MoneyField()
    gst_amount = MoneyField()
    total_amount = MoneyField()
    tds_rate = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    tds_amount = MoneyField()
    net_payable = MoneyField(
        help_text="Total less the TDS we deduct and the retention we hold: what we pay"
    )
    work_order_id = serializers.UUIDField(allow_null=True)
    wo_number = serializers.CharField(
        source="work_order.wo_number", allow_null=True, read_only=True, default=None
    )
    retention_amount = MoneyField(help_text="Held back on an RA bill (work order retention)")
    amount_paid = MoneyField()
    outstanding = serializers.SerializerMethodField()
    attachment_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = VendorBill
        fields: tuple[str, ...] = (
            "id",
            "version",
            "vendor_party_id",
            "vendor_name",
            "project_id",
            "project_name",
            "bill_number",
            "bill_date",
            "due_date",
            "category",
            "description",
            "taxable_value",
            "gst_amount",
            "total_amount",
            "itc_eligible",
            "tds_section",
            "tds_rate",
            "tds_amount",
            "net_payable",
            "work_order_id",
            "wo_number",
            "ra_number",
            "retention_amount",
            "amount_paid",
            "outstanding",
            "attachment_id",
            "notes",
            "status",
            "voided_at",
            "void_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_outstanding(self, obj: VendorBill) -> str:
        if obj.status != "RECORDED":
            return "0.00"
        return f"{obj.net_payable - obj.amount_paid:.2f}"


class VendorAllocationInSerializer(serializers.Serializer[Any]):
    vendor_bill_id = serializers.UUIDField(required=False, allow_null=True)
    vendor_retention_release_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Or retention released to a subcontractor"
    )
    amount = MoneyField(min_value=PAISA)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get("vendor_bill_id")) == bool(attrs.get("vendor_retention_release_id")):
            raise serializers.ValidationError(
                {"vendor_bill_id": "Give a vendor bill or a retention release (one of them)."},
                code="required",
            )
        return attrs


class VendorPaymentCreateSerializer(serializers.Serializer[Any]):
    vendor_party_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, allow_null=True)
    payment_date = serializers.DateField()
    amount = MoneyField(min_value=PAISA)
    mode = serializers.ChoiceField(choices=PaymentMode.choices)
    reference = serializers.CharField(
        max_length=100, required=False, allow_null=True, help_text="UTR / cheque number"
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)
    allocations = VendorAllocationInSerializer(many=True, required=False)


class VendorAllocationOutSerializer(serializers.ModelSerializer[VendorAllocation]):
    vendor_bill_id = serializers.UUIDField(allow_null=True)
    vendor_retention_release_id = serializers.UUIDField(allow_null=True)
    bill_number = serializers.SerializerMethodField(
        help_text="The bill's number, or 'Retention, WO/...' for a release"
    )
    amount = MoneyField()

    class Meta:
        model = VendorAllocation
        fields = (
            "id",
            "vendor_bill_id",
            "vendor_retention_release_id",
            "bill_number",
            "amount",
            "created_at",
        )
        read_only_fields = fields

    def get_bill_number(self, obj: VendorAllocation) -> str:
        if obj.vendor_bill is not None:
            return str(obj.vendor_bill.bill_number)
        release = obj.vendor_retention_release
        return f"Retention, {release.work_order.wo_number}" if release else ""


class VendorPaymentSerializer(serializers.ModelSerializer[VendorPayment]):
    vendor_party_id = serializers.UUIDField()
    vendor_name = serializers.CharField(source="vendor_party.display_name", read_only=True)
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    amount = MoneyField()
    unallocated = serializers.SerializerMethodField()
    allocations = serializers.SerializerMethodField()

    class Meta:
        model = VendorPayment
        fields = (
            "id",
            "version",
            "vendor_party_id",
            "vendor_name",
            "project_id",
            "project_name",
            "payment_date",
            "amount",
            "mode",
            "reference",
            "notes",
            "status",
            "unallocated",
            "allocations",
            "voided_at",
            "void_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def _allocations(self, obj: VendorPayment) -> list[VendorAllocation]:
        return list(obj.allocations.all())

    def get_unallocated(self, obj: VendorPayment) -> str:
        if obj.status != "RECORDED":
            return "0.00"
        used = sum((a.amount for a in self._allocations(obj)), Decimal("0.00"))
        return f"{obj.amount - used:.2f}"

    @extend_schema_field(VendorAllocationOutSerializer(many=True))
    def get_allocations(self, obj: VendorPayment) -> list[dict[str, Any]]:
        return list(VendorAllocationOutSerializer(self._allocations(obj), many=True).data)


class TdsQuerySerializer(serializers.Serializer[Any]):
    vendor_party_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=ExpenseCategory.choices)
    taxable_value = MoneyField(min_value=Decimal("0.00"))
    bill_date = serializers.DateField()
    vendor_bill_id = serializers.UUIDField(
        required=False, help_text="When editing: leave this bill out of the year's total"
    )


class TdsSuggestionSerializer(serializers.Serializer[Any]):
    section = serializers.CharField(allow_null=True, help_text="Null: no TDS suggested")
    rate = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    amount = MoneyField()
    reason = serializers.CharField(help_text="Why, in words")
    year_total = MoneyField(help_text="The vendor's bills this financial year, before this one")


class PayableSerializer(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    display_name = serializers.CharField()
    bill_count = serializers.IntegerField()
    not_due = MoneyField()
    days_1_30 = MoneyField()
    days_31_60 = MoneyField()
    days_61_90 = MoneyField()
    days_90_plus = MoneyField()
    total = MoneyField()


class PayablesSerializer(serializers.Serializer[Any]):
    as_of = serializers.DateField()
    results = PayableSerializer(many=True)
    totals = PayableSerializer()


# --- subcontract work orders and RA bills (payables part 2) -------------------

QTY: dict[str, Any] = {"max_digits": 14, "decimal_places": 3, "coerce_to_string": True}
PERCENT: dict[str, Any] = {"max_digits": 5, "decimal_places": 2, "coerce_to_string": True}


class WorkOrderItemWriteSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(required=False, help_text="Edit: an existing item; omit for new")
    boq_item_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="The client's BOQ item this work is part of"
    )
    item_code = serializers.CharField(max_length=30)
    description = serializers.CharField(max_length=2000)
    unit = serializers.CharField(max_length=20)
    sac_hsn = serializers.RegexField(r"^[0-9]{4,8}$", required=False, allow_null=True)
    qty = serializers.DecimalField(**QTY, min_value=Decimal("0.001"), help_text="Agreed")
    rate = MoneyField(min_value=Decimal("0.00"))
    gst_rate = serializers.DecimalField(
        **PERCENT, min_value=Decimal("0"), max_value=Decimal("50"), default=Decimal("18")
    )


class WorkOrderUpdateSerializer(serializers.Serializer[Any]):
    """Edit: the terms and the items (not the project or the subcontractor)."""

    wo_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    wo_date = serializers.DateField(required=False)
    title = serializers.CharField(max_length=200, required=False)
    terms = serializers.CharField(max_length=4000, required=False, allow_null=True)
    retention_pct = serializers.DecimalField(
        **PERCENT, min_value=Decimal("0"), max_value=Decimal("20"), required=False
    )
    tds_section = serializers.RegexField(SECTION, required=False, allow_null=True)
    tds_rate = serializers.DecimalField(
        **PERCENT, min_value=Decimal("0"), max_value=Decimal("30"), required=False, allow_null=True
    )
    items = WorkOrderItemWriteSerializer(
        many=True, required=False, help_text="The whole list: items left out are removed"
    )


class WorkOrderWriteSerializer(WorkOrderUpdateSerializer):
    project_id = serializers.UUIDField()
    vendor_party_id = serializers.UUIDField(help_text="The subcontractor")
    wo_number = serializers.CharField(
        max_length=30, required=False, allow_blank=True, help_text="Ours; empty: WO/<project>/NN"
    )
    wo_date = serializers.DateField()
    title = serializers.CharField(max_length=200, help_text="The scope in a line")
    retention_pct = serializers.DecimalField(
        **PERCENT, min_value=Decimal("0"), max_value=Decimal("20"), default=Decimal("0")
    )
    items = WorkOrderItemWriteSerializer(many=True)


class WorkOrderItemSerializer(serializers.ModelSerializer[WorkOrderItem]):
    boq_item_id = serializers.UUIDField(allow_null=True)
    boq_item_code = serializers.CharField(
        source="boq_item.item_code", allow_null=True, read_only=True, default=None
    )
    qty = serializers.DecimalField(**QTY)
    rate = MoneyField()
    gst_rate = serializers.DecimalField(**PERCENT)
    amount = serializers.SerializerMethodField(help_text="qty x rate")
    billed_qty = serializers.SerializerMethodField(help_text="On recorded RA bills so far")
    balance_qty = serializers.SerializerMethodField(help_text="Still to be billed")

    class Meta:
        model = WorkOrderItem
        fields = (
            "id",
            "boq_item_id",
            "boq_item_code",
            "item_code",
            "description",
            "unit",
            "sac_hsn",
            "qty",
            "rate",
            "gst_rate",
            "amount",
            "billed_qty",
            "balance_qty",
        )
        read_only_fields = fields

    def _billed(self, obj: WorkOrderItem) -> Decimal:
        billed: dict[Any, Decimal] = self.context.get("billed", {})
        return billed.get(obj.pk, Decimal("0"))

    def get_amount(self, obj: WorkOrderItem) -> str:
        return f"{(obj.qty * obj.rate).quantize(PAISA, rounding=ROUND_HALF_UP):.2f}"

    def get_billed_qty(self, obj: WorkOrderItem) -> str:
        return f"{self._billed(obj):.3f}"

    def get_balance_qty(self, obj: WorkOrderItem) -> str:
        return f"{obj.qty - self._billed(obj):.3f}"


class RaBillSummarySerializer(serializers.ModelSerializer[VendorBill]):
    taxable_value = MoneyField()
    retention_amount = MoneyField()
    net_payable = MoneyField()
    amount_paid = MoneyField()

    class Meta:
        model = VendorBill
        fields = (
            "id",
            "ra_number",
            "bill_number",
            "bill_date",
            "taxable_value",
            "retention_amount",
            "net_payable",
            "amount_paid",
            "status",
        )
        read_only_fields = fields


class WorkOrderSerializer(serializers.ModelSerializer[WorkOrder]):
    project_id = serializers.UUIDField()
    project_code = serializers.CharField(source="project.code", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    vendor_party_id = serializers.UUIDField()
    vendor_name = serializers.CharField(source="vendor_party.display_name", read_only=True)
    retention_pct = serializers.DecimalField(**PERCENT)
    tds_rate = serializers.DecimalField(**PERCENT)
    value = MoneyField(source="totals.value", help_text="qty x rate of every item")
    billed = MoneyField(source="totals.billed", help_text="Recorded RA bills, before GST")
    retention_held = MoneyField(
        source="totals.retention_held", help_text="On recorded RA bills, all told"
    )
    retention_released = MoneyField(source="totals.retention_released")
    retention_to_release = MoneyField(
        source="totals.retention_to_release", help_text="Held and not yet released"
    )
    paid = MoneyField(source="totals.paid", help_text="Paid on its RA bills")
    ra_count = serializers.IntegerField(source="totals.ra_count")

    class Meta:
        model = WorkOrder
        fields: tuple[str, ...] = (
            "id",
            "version",
            "project_id",
            "project_code",
            "project_name",
            "vendor_party_id",
            "vendor_name",
            "wo_number",
            "wo_date",
            "title",
            "terms",
            "retention_pct",
            "tds_section",
            "tds_rate",
            "status",
            "value",
            "billed",
            "retention_held",
            "retention_released",
            "retention_to_release",
            "paid",
            "ra_count",
            "created_at",
            "updated_at",
        )
        read_only_fields: tuple[str, ...] = fields


class VendorRetentionReleaseSerializer(serializers.ModelSerializer[VendorRetentionRelease]):
    work_order_id = serializers.UUIDField()
    wo_number = serializers.CharField(source="work_order.wo_number", read_only=True)
    vendor_party_id = serializers.UUIDField()
    vendor_name = serializers.CharField(source="vendor_party.display_name", read_only=True)
    amount = MoneyField()
    amount_paid = MoneyField()
    outstanding = serializers.SerializerMethodField()

    class Meta:
        model = VendorRetentionRelease
        fields = (
            "id",
            "version",
            "work_order_id",
            "wo_number",
            "vendor_party_id",
            "vendor_name",
            "release_date",
            "due_date",
            "amount",
            "amount_paid",
            "outstanding",
            "reference",
            "notes",
            "status",
            "cancelled_at",
            "cancel_reason",
            "created_at",
        )
        read_only_fields = fields

    def get_outstanding(self, obj: VendorRetentionRelease) -> str:
        if obj.status != "RELEASED":
            return "0.00"
        return f"{obj.amount - obj.amount_paid:.2f}"


class RetentionReleaseWriteSerializer(serializers.Serializer[Any]):
    release_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    amount = MoneyField(min_value=PAISA, help_text="At most the retention still held")
    reference = serializers.CharField(max_length=50, required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)


class WorkOrderDetailSerializer(WorkOrderSerializer):
    items = serializers.SerializerMethodField()
    ra_bills = serializers.SerializerMethodField()
    releases = serializers.SerializerMethodField()

    class Meta(WorkOrderSerializer.Meta):
        fields = (*WorkOrderSerializer.Meta.fields, "items", "ra_bills", "releases")
        read_only_fields = fields

    @extend_schema_field(WorkOrderItemSerializer(many=True))
    def get_items(self, obj: WorkOrder) -> Any:
        from . import work_orders

        context = {"billed": work_orders.billed_qty(obj)}
        items = WorkOrderItem.objects.filter(work_order=obj).select_related("boq_item")
        return WorkOrderItemSerializer(
            items.order_by("sort_order", "item_code"), many=True, context=context
        ).data

    @extend_schema_field(RaBillSummarySerializer(many=True))
    def get_ra_bills(self, obj: WorkOrder) -> Any:
        bills = VendorBill.objects.filter(work_order=obj).order_by("ra_number", "created_at")
        return RaBillSummarySerializer(bills, many=True).data

    @extend_schema_field(VendorRetentionReleaseSerializer(many=True))
    def get_releases(self, obj: WorkOrder) -> Any:
        releases = VendorRetentionRelease.objects.filter(work_order=obj).select_related(
            "work_order", "vendor_party"
        )
        return VendorRetentionReleaseSerializer(
            releases.order_by("release_date", "created_at"), many=True
        ).data


class RaBillLineInSerializer(serializers.Serializer[Any]):
    work_order_item_id = serializers.UUIDField()
    qty = serializers.DecimalField(
        **QTY, min_value=Decimal("0.001"), help_text="This bill's quantity (not the total to date)"
    )


class RaBillWriteSerializer(serializers.Serializer[Any]):
    bill_number = serializers.CharField(max_length=50, help_text="The subcontractor's own number")
    bill_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    ra_number = serializers.IntegerField(
        min_value=1, required=False, help_text="Default: the next after the last recorded"
    )
    category = serializers.ChoiceField(
        choices=ExpenseCategory.choices, required=False, help_text="Default SUBCONTRACT"
    )
    itc_eligible = serializers.BooleanField(required=False)
    attachment_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_null=True)
    lines = RaBillLineInSerializer(many=True)


class VendorBillLineSerializer(serializers.ModelSerializer[VendorBillLine]):
    work_order_item_id = serializers.UUIDField()
    item_code = serializers.CharField(source="work_order_item.item_code", read_only=True)
    description = serializers.CharField(source="work_order_item.description", read_only=True)
    unit = serializers.CharField(source="work_order_item.unit", read_only=True)
    qty = serializers.DecimalField(**QTY)
    rate = MoneyField()
    amount = MoneyField()
    gst_rate = serializers.DecimalField(**PERCENT)

    class Meta:
        model = VendorBillLine
        fields = (
            "id",
            "work_order_item_id",
            "item_code",
            "description",
            "unit",
            "qty",
            "rate",
            "amount",
            "gst_rate",
        )
        read_only_fields = fields


class VendorBillDetailSerializer(VendorBillSerializer):
    lines = VendorBillLineSerializer(
        many=True, read_only=True, help_text="An RA bill's quantities; empty for other bills"
    )

    class Meta(VendorBillSerializer.Meta):
        fields = (*VendorBillSerializer.Meta.fields, "lines")
        read_only_fields = fields
