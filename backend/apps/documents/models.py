"""Billing documents: ONE table for every type (see db/schema.sql §4).

"GST books", "estimates" and the "combined view" are filters over it
(is_gst_document / is_revenue), not separate modules.
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import ExpressionWrapper, F, Func, Q
from django.db.models.functions import Round
from django.db.models.lookups import Exact

from apps.core.db import (
    CITextField,
    FixedCharField,
    between,
    created_at,
    length_between,
    non_negative,
    one_of,
    ref,
    regex,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)
from apps.core.managers import TenantScoped
from apps.projects.models import SAC_HSN_RE
from apps.tenants.models import STATE_CODE_RE, DocType

GST_DOC_TYPES = ["TAX_INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"]
NON_REVENUE_DOC_TYPES = ["QUOTATION", "PROFORMA"]


def _money(**kwargs: object) -> models.DecimalField:  # type: ignore[type-arg]
    return models.DecimalField(max_digits=14, decimal_places=2, **kwargs)  # type: ignore[arg-type]


def _money_zero() -> models.DecimalField:  # type: ignore[type-arg]
    return _money(default=0, db_default=0)


class DocumentSupplyType(models.TextChoices):
    INTRA_STATE = "INTRA_STATE"
    INTER_STATE = "INTER_STATE"


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class SupplyCategory(models.TextChoices):
    REGULAR = "REGULAR"
    SEZ = "SEZ"  # to an SEZ unit / developer: always inter-State (IGST Act s.7(5)(b))
    EXPORT = "EXPORT"  # recipient outside India, no Indian site: place of supply 96


class Document(TenantScoped):
    Status = DocumentStatus
    SupplyType = DocumentSupplyType
    id = uuid7_pk()
    tenant = tenant_ref()
    doc_type = models.TextField(choices=DocType)
    status = models.TextField(
        choices=Status, default=DocumentStatus.DRAFT, db_default=DocumentStatus.DRAFT
    )
    gst_registration = ref("tenants.GstRegistration")
    series = ref("tenants.DocumentSeries", null=True)
    doc_number = models.CharField(max_length=16, null=True)  # noqa: DJ001 - NULL until issued
    doc_date = models.DateField()
    fy_start_year = models.GeneratedField(
        # SQL function from the core migration: India's FY starts 1 April.
        expression=Func(
            F("doc_date"), function="fy_start_year", output_field=models.SmallIntegerField()
        ),
        output_field=models.SmallIntegerField(),
        db_persist=True,
    )
    due_date = models.DateField(null=True)
    valid_until = models.DateField(null=True)  # quotations
    party = ref("parties.Party")
    project = ref("projects.Project", null=True)
    source_document = ref("documents.Document", null=True)  # converted from (quotation/proforma)
    original_document = ref("documents.Document", null=True)  # adjusted by this credit/debit note
    is_ra_bill = models.BooleanField(default=False, db_default=False)
    ra_sequence = models.IntegerField(null=True)
    # Frozen copies taken at issue, so later edits never change an issued document.
    supplier_snapshot = models.JSONField(null=True)
    party_snapshot = models.JSONField(null=True)
    place_of_supply = FixedCharField(max_length=2)
    supply_type = models.TextField(choices=SupplyType)
    reverse_charge = models.BooleanField(default=False, db_default=False)
    supply_category = models.TextField(
        choices=SupplyCategory, default=SupplyCategory.REGULAR, db_default=SupplyCategory.REGULAR
    )
    lut = models.BooleanField(default=False, db_default=False)
    # Totals: computed by the tax engine on every draft save, verified against
    # the lines when the document is issued (trigger documents_guard).
    subtotal = _money_zero()
    cgst_amount = _money_zero()
    sgst_amount = _money_zero()
    igst_amount = _money_zero()
    cess_amount = _money_zero()
    round_off = models.DecimalField(max_digits=4, decimal_places=2, default=0, db_default=0)
    round_to_rupee = models.BooleanField(default=False, db_default=False)  # kept for recompute
    grand_total = _money_zero()
    # Construction deductions: they reduce what the client pays now, not the taxable value.
    retention_amount = _money_zero()
    income_tax_tds_amount = _money_zero()
    gst_tds_amount = _money_zero()
    advance_recovery_amount = _money_zero()
    net_receivable = _money_zero()
    # Maintained only by the allocations trigger; the app role cannot UPDATE it.
    amount_settled = _money_zero()
    is_gst_document = models.GeneratedField(
        expression=ExpressionWrapper(
            Q(doc_type__in=GST_DOC_TYPES), output_field=models.BooleanField()
        ),
        output_field=models.BooleanField(),
        db_persist=True,
    )
    is_revenue = models.GeneratedField(
        expression=ExpressionWrapper(
            Q(doc_type__not_in=NON_REVENUE_DOC_TYPES), output_field=models.BooleanField()
        ),
        output_field=models.BooleanField(),
        db_persist=True,
    )
    notes = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    terms = models.TextField(null=True)  # noqa: DJ001
    pdf_attachment = ref("files.Attachment", null=True)
    issued_at = models.DateTimeField(null=True)
    issued_by = ref("accounts.User", null=True, db_column="issued_by")
    cancelled_at = models.DateTimeField(null=True)
    cancelled_by = ref("accounts.User", null=True, db_column="cancelled_by")
    cancel_reason = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "documents"
        constraints = [
            tenant_id_key("documents"),
            one_of("doc_type", DocType.values, "documents_doc_type_check"),
            one_of("status", DocumentStatus.values, "documents_status_check"),
            regex("doc_number", r"^[A-Za-z0-9/-]{1,16}$", "documents_doc_number_check"),
            models.CheckConstraint(
                condition=Q(ra_sequence__gt=0), name="documents_ra_sequence_check"
            ),
            regex("place_of_supply", STATE_CODE_RE, "documents_place_of_supply_check"),
            one_of("supply_type", DocumentSupplyType.values, "documents_supply_type_check"),
            *(
                non_negative(f, f"documents_{f}_check")
                for f in [
                    "subtotal",
                    "cgst_amount",
                    "sgst_amount",
                    "igst_amount",
                    "cess_amount",
                    "retention_amount",
                    "income_tax_tds_amount",
                    "gst_tds_amount",
                    "advance_recovery_amount",
                    "net_receivable",
                ]
            ),
            between("round_off", -1, 1, "documents_round_off_check"),
            # anything past DRAFT must be fully numbered and snapshotted
            models.CheckConstraint(
                condition=Q(status="DRAFT")
                | (
                    Q(doc_number__isnull=False)
                    & Q(series__isnull=False)
                    & Q(issued_at__isnull=False)
                    & Q(issued_by__isnull=False)
                    & Q(supplier_snapshot__isnull=False)
                    & Q(party_snapshot__isnull=False)
                ),
                name="documents_issued_complete_check",
            ),
            # numbers are assigned at issue, never on drafts
            models.CheckConstraint(
                condition=Q(status__ne="DRAFT") | Q(doc_number__isnull=True),
                name="documents_draft_unnumbered_check",
            ),
            models.CheckConstraint(
                condition=Q(status__not_in=["ACCEPTED", "DECLINED"]) | Q(doc_type="QUOTATION"),
                name="documents_quotation_status_check",
            ),
            models.CheckConstraint(
                condition=Q(status__ne="CANCELLED")
                | (
                    Q(cancelled_at__isnull=False)
                    & Q(cancel_reason__isnull=False)
                    & Q(amount_settled=0)
                ),
                name="documents_cancel_check",
            ),
            models.CheckConstraint(
                condition=Q(original_document__isnull=True)
                | Q(doc_type__in=["CREDIT_NOTE", "DEBIT_NOTE"]),
                name="documents_original_document_check",
            ),
            models.CheckConstraint(
                condition=Exact(
                    F("is_ra_bill"),
                    ExpressionWrapper(
                        Q(ra_sequence__isnull=False), output_field=models.BooleanField()
                    ),
                ),
                name="documents_ra_sequence_iff_ra_bill",
            ),
            models.CheckConstraint(
                condition=Q(is_ra_bill=False)
                | (
                    Q(doc_type__in=["PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"])
                    & Q(project__isnull=False)
                ),
                name="documents_ra_bill_check",
            ),
            # tax arithmetic
            models.CheckConstraint(
                condition=Q(cgst_amount=F("sgst_amount")), name="documents_cgst_sgst_check"
            ),
            models.CheckConstraint(
                condition=Q(supply_type="INTRA_STATE") | (Q(cgst_amount=0) & Q(sgst_amount=0)),
                name="documents_inter_state_tax_check",
            ),
            models.CheckConstraint(
                condition=Q(supply_type="INTER_STATE") | Q(igst_amount=0),
                name="documents_intra_state_tax_check",
            ),
            models.CheckConstraint(
                condition=Q(doc_type__ne="BILL_OF_SUPPLY")
                | (Q(cgst_amount=0) & Q(igst_amount=0) & Q(cess_amount=0)),
                name="documents_bill_of_supply_tax_check",
            ),
            one_of("supply_category", SupplyCategory.values, "documents_supply_category_check"),
            # grand total, LUT and reverse-charge rules: SQL in migration 0003 (db/schema.sql §4)
            models.CheckConstraint(
                condition=Q(
                    net_receivable=F("grand_total")
                    - F("retention_amount")
                    - F("income_tax_tds_amount")
                    - F("gst_tds_amount")
                    - F("advance_recovery_amount")
                ),
                name="documents_net_receivable_calc_check",
            ),
            models.CheckConstraint(
                condition=Q(amount_settled__gte=0) & Q(amount_settled__lte=F("net_receivable")),
                name="documents_amount_settled_check",
            ),
            models.CheckConstraint(
                condition=Q(due_date__isnull=True) | Q(due_date__gte=F("doc_date")),
                name="documents_due_date_check",
            ),
            # GST: numbers unique per registration (GSTIN) per financial year.
            models.UniqueConstraint(
                fields=["tenant", "gst_registration", "fy_start_year", "doc_number"],
                condition=Q(doc_number__isnull=False),
                name="documents_number_uq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "project", "doc_type", "ra_sequence"],
                condition=Q(is_ra_bill=True) & Q(status__ne="CANCELLED"),
                name="documents_ra_sequence_uq",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "-doc_date"], name="documents_date_idx"),
            models.Index(fields=["tenant", "party", "-doc_date"], name="documents_party_idx"),
            models.Index(
                fields=["tenant", "project", "-doc_date"],
                condition=Q(project__isnull=False),
                name="documents_project_idx",
            ),
            models.Index(fields=["tenant", "doc_type", "status"], name="documents_type_idx"),
            models.Index(
                fields=["tenant", "due_date"],
                condition=Q(status="ISSUED")
                & Q(is_revenue=True)
                & Q(amount_settled__lt=F("net_receivable")),
                name="documents_open_idx",
            ),
            GinIndex(
                fields=["doc_number"],
                opclasses=["gin_trgm_ops"],
                condition=Q(doc_number__isnull=False),
                name="documents_number_trgm_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.doc_type} {self.doc_number or '(draft)'}"


class DocumentLine(TenantScoped):
    id = uuid7_pk()
    tenant = tenant_ref()
    # CASCADE: only drafts can be deleted (trigger), and their lines go with them.
    document = ref("documents.Document", related_name="lines", on_delete=models.CASCADE)
    line_no = models.SmallIntegerField()
    catalog_item = ref("catalog.CatalogItem", null=True)
    catalog_variant = ref("catalog.CatalogItemVariant", null=True)
    boq_item = ref("projects.BoqItem", null=True)
    description = models.TextField()
    sac_hsn = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    unit = models.TextField(null=True)  # noqa: DJ001
    quantity = models.DecimalField(max_digits=14, decimal_places=3)  # RA bill: in THIS bill
    prev_cumulative_qty = models.DecimalField(  # RA bill: billed up to the previous bill
        max_digits=14, decimal_places=3, null=True
    )
    rate = _money()
    discount_amount = _money_zero()
    # B.5: a discount given as a percentage; discount_amount is worked out from it
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    taxable_value = _money()
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, db_default=0)
    cgst_amount = _money_zero()
    sgst_amount = _money_zero()
    igst_amount = _money_zero()
    cess_amount = _money_zero()
    line_total = _money()

    class Meta:
        db_table = "document_lines"
        constraints = [
            tenant_id_key("document_lines"),
            models.UniqueConstraint(
                fields=["document", "line_no"], name="document_lines_document_id_line_no_key"
            ),
            models.CheckConstraint(condition=Q(line_no__gt=0), name="document_lines_line_no_check"),
            length_between("description", 1, 2000, "document_lines_description_check"),
            regex("sac_hsn", SAC_HSN_RE, "document_lines_sac_hsn_check"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="document_lines_quantity_check"
            ),
            non_negative("prev_cumulative_qty", "document_lines_prev_cumulative_qty_check"),
            non_negative("rate", "document_lines_rate_check"),
            non_negative("discount_amount", "document_lines_discount_amount_check"),
            between("discount_pct", 0, 100, "document_lines_discount_pct_check"),
            non_negative("taxable_value", "document_lines_taxable_value_check"),
            between("gst_rate", 0, 50, "document_lines_gst_rate_check"),
            non_negative("cgst_amount", "document_lines_cgst_amount_check"),
            non_negative("sgst_amount", "document_lines_sgst_amount_check"),
            non_negative("igst_amount", "document_lines_igst_amount_check"),
            non_negative("cess_amount", "document_lines_cess_amount_check"),
            models.CheckConstraint(
                condition=Q(
                    taxable_value=Round(F("quantity") * F("rate"), 2) - F("discount_amount")
                ),
                name="document_lines_taxable_value_calc_check",
            ),
            models.CheckConstraint(
                condition=Q(cgst_amount=F("sgst_amount")), name="document_lines_cgst_sgst_check"
            ),
            models.CheckConstraint(
                condition=Q(
                    line_total=F("taxable_value")
                    + F("cgst_amount")
                    + F("sgst_amount")
                    + F("igst_amount")
                    + F("cess_amount")
                ),
                name="document_lines_line_total_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "boq_item"],
                condition=Q(boq_item__isnull=False),
                name="document_lines_boq_idx",
            ),
            # B.1 / B.8: an item's last use, and the rate last charged to a client
            models.Index(
                fields=["tenant", "catalog_item"],
                condition=Q(catalog_item__isnull=False),
                name="document_lines_catalog_idx",
            ),
        ]


class DocumentLineMeasurement(TenantScoped):
    """A measurement-sheet row of a bill line (B.9): number x length x breadth x
    height (empty sizes count as 1), rounded half up to 3 decimals; a "deduct"
    row (an opening, say) takes its quantity off. The line's quantity is the
    total. Rows change with their line, so only while the bill is a draft (the
    document_lines_guard trigger, on this table too)."""

    id = uuid7_pk()
    tenant = tenant_ref()
    # rows go with their line or draft (also ON DELETE CASCADE in the database)
    document = ref("documents.Document", on_delete=models.CASCADE)
    line = ref("documents.DocumentLine", related_name="measurements", on_delete=models.CASCADE)
    row_no = models.SmallIntegerField()
    description = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    nos = models.DecimalField(max_digits=14, decimal_places=3, default=1, db_default=1)
    length = models.DecimalField(max_digits=14, decimal_places=3, null=True)
    breadth = models.DecimalField(max_digits=14, decimal_places=3, null=True)
    height = models.DecimalField(max_digits=14, decimal_places=3, null=True)
    deduct = models.BooleanField(default=False, db_default=False)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        db_table = "document_line_measurements"
        constraints = [
            models.CheckConstraint(
                condition=Q(row_no__gt=0), name="document_line_measurements_row_no_check"
            ),
            models.CheckConstraint(
                condition=Q(description__char_length__lte=500),
                name="document_line_measurements_description_check",
            ),
            models.CheckConstraint(
                condition=Q(nos__gt=0), name="document_line_measurements_nos_check"
            ),
            models.CheckConstraint(
                condition=Q(length__gt=0), name="document_line_measurements_length_check"
            ),
            models.CheckConstraint(
                condition=Q(breadth__gt=0), name="document_line_measurements_breadth_check"
            ),
            models.CheckConstraint(
                condition=Q(height__gt=0), name="document_line_measurements_height_check"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="document_line_measurements_quantity_check"
            ),
            models.UniqueConstraint(
                fields=["line", "row_no"], name="document_line_measurements_line_id_row_no_key"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "line"], name="line_measurements_line_idx")]


class DocumentEmailCopy(models.TextChoices):
    ORIGINAL = "original"
    DUPLICATE = "duplicate"
    TRIPLICATE = "triplicate"


class DocumentEmail(TenantScoped):
    """A bill emailed to a client with its PDF (B.15). A log: written once."""

    Copy = DocumentEmailCopy
    id = uuid7_pk()
    tenant = tenant_ref()
    document = ref("documents.Document")
    sent_to = CITextField()
    copy = models.TextField(choices=DocumentEmailCopy)
    sent_by = ref("accounts.User", db_column="sent_by")
    sent_at = created_at()

    class Meta:
        db_table = "document_emails"
        constraints = [
            tenant_id_key("document_emails"),
            length_between("sent_to", 3, 254, "document_emails_sent_to_check"),
            one_of("copy", DocumentEmailCopy.values, "document_emails_copy_check"),
        ]
        indexes = [
            models.Index(fields=["tenant", "document", "-sent_at"], name="document_emails_doc_idx")
        ]
