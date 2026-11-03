from django.db import models
from django.db.models import Q

from apps.core.db import (
    CharLength,
    FixedCharField,
    between,
    created_at,
    length_between,
    one_of,
    ref,
    regex,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)
from apps.core.managers import TenantScoped

PAN_RE = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
GSTIN_RE = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
STATE_CODE_RE = r"^[0-9]{2}$"


class DocType(models.TextChoices):
    QUOTATION = "QUOTATION"
    PROFORMA = "PROFORMA"
    TAX_INVOICE = "TAX_INVOICE"
    BILL_OF_SUPPLY = "BILL_OF_SUPPLY"
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"


class TenantStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Tenant(models.Model):
    """One business. Global table, protected by RLS (tenant_self / tenant_member_read)."""

    Status = TenantStatus
    id = uuid7_pk()
    legal_name = models.TextField()
    trade_name = models.TextField(null=True)  # noqa: DJ001 - mirrors schema (NULL = not set)
    pan = FixedCharField(max_length=10, null=True)
    status = models.TextField(
        choices=Status, default=TenantStatus.ACTIVE, db_default=TenantStatus.ACTIVE
    )
    plan = models.TextField(default="FREE", db_default="FREE")
    timezone = models.TextField(default="Asia/Kolkata", db_default="Asia/Kolkata")
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "tenants"
        constraints = [
            length_between("legal_name", 1, 200, "tenants_legal_name_check"),
            regex("pan", PAN_RE, "tenants_pan_check"),
            one_of("status", TenantStatus.values, "tenants_status_check"),
        ]

    def __str__(self) -> str:
        return self.legal_name


class GstRegistrationRegistrationType(models.TextChoices):
    REGULAR = "REGULAR"
    COMPOSITION = "COMPOSITION"
    UNREGISTERED = "UNREGISTERED"


class GstRegistration(TenantScoped):
    """Our GSTIN in one state (a business can hold one per state, or none)."""

    RegistrationType = GstRegistrationRegistrationType
    id = uuid7_pk()
    tenant = tenant_ref()
    registration_type = models.TextField(choices=RegistrationType)
    gstin = models.CharField(max_length=15, null=True)  # noqa: DJ001
    state_code = FixedCharField(max_length=2)
    legal_name = models.TextField()
    trade_name = models.TextField(null=True)  # noqa: DJ001
    address = models.JSONField()
    is_default = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True, db_default=True)
    # Letter of Undertaking for one financial year: zero-rated supplies without IGST.
    lut_arn = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    lut_fy_start_year = models.SmallIntegerField(null=True)
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "gst_registrations"
        constraints = [
            tenant_id_key("gst_registrations"),
            one_of(
                "registration_type",
                GstRegistrationRegistrationType.values,
                "gst_registrations_type_check",
            ),
            regex("gstin", GSTIN_RE, "gst_registrations_gstin_check"),
            regex("state_code", STATE_CODE_RE, "gst_registrations_state_code_check"),
            models.CheckConstraint(
                condition=models.lookups.Exact(
                    models.ExpressionWrapper(
                        Q(registration_type="UNREGISTERED"), output_field=models.BooleanField()
                    ),
                    models.ExpressionWrapper(
                        Q(gstin__isnull=True), output_field=models.BooleanField()
                    ),
                ),
                name="gst_registrations_gstin_iff_registered",
            ),
            models.CheckConstraint(
                condition=Q(gstin__isnull=True) | Q(gstin__state_prefix=models.F("state_code")),
                name="gst_registrations_gstin_state_check",
            ),
            models.UniqueConstraint(
                fields=["tenant", "gstin"],
                condition=Q(gstin__isnull=False),
                name="gst_registrations_gstin_uq",
            ),
            models.UniqueConstraint(
                fields=["tenant"], condition=Q(is_default=True), name="gst_registrations_default_uq"
            ),
            regex("lut_arn", r"^[A-Z0-9]{15}$", "gst_registrations_lut_arn_check"),
            between("lut_fy_start_year", 2017, 2100, "gst_registrations_lut_fy_check"),
            models.CheckConstraint(
                condition=Q(lut_arn__isnull=True, lut_fy_start_year__isnull=True)
                | Q(lut_arn__isnull=False, lut_fy_start_year__isnull=False),
                name="gst_registrations_lut_complete_check",
            ),
        ]


class DocumentSeries(TenantScoped):
    """Number series per registration, document type and financial year."""

    id = uuid7_pk()
    tenant = tenant_ref()
    gst_registration = ref("tenants.GstRegistration")
    doc_type = models.TextField(choices=DocType)
    fy_start_year = models.SmallIntegerField()
    prefix = models.TextField(default="", db_default="", blank=True)
    next_number = models.IntegerField(default=1, db_default=1)
    pad_width = models.SmallIntegerField(default=4, db_default=4)
    is_active = models.BooleanField(default=True, db_default=True)
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "document_series"
        constraints = [
            tenant_id_key("document_series"),
            one_of("doc_type", DocType.values, "document_series_doc_type_check"),
            between("fy_start_year", 2000, 2100, "document_series_fy_start_year_check"),
            regex("prefix", r"^[A-Za-z0-9/-]{0,10}$", "document_series_prefix_check"),
            models.CheckConstraint(
                condition=Q(next_number__gt=0), name="document_series_next_number_check"
            ),
            between("pad_width", 1, 8, "document_series_pad_width_check"),
            models.UniqueConstraint(
                fields=["tenant", "gst_registration", "doc_type", "fy_start_year", "prefix"],
                name="document_series_unique_per_fy",
            ),
            # Issuing picks "the" active series for a registration, type and year.
            models.UniqueConstraint(
                fields=["tenant", "gst_registration", "doc_type", "fy_start_year"],
                condition=Q(is_active=True),
                name="document_series_active_uq",
            ),
            # GST: an invoice number is at most 16 characters.
            models.CheckConstraint(
                condition=models.lookups.LessThanOrEqual(
                    CharLength("prefix") + models.F("pad_width"), 16
                ),
                name="document_series_number_length_check",
            ),
        ]


class PrintLayout(models.TextChoices):
    SIMPLE = "SIMPLE"  # one table: item, quantity, rate, amount; the tax in the totals
    DETAILED = "DETAILED"  # every column, the HSN / tax breakup and measurement rows


IFSC_RE = r"^[A-Z]{4}0[A-Z0-9]{6}$"
BANK_ACCOUNT_RE = r"^[0-9]{6,18}$"
UPI_RE = r"^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,63}$"


class PrintSettings(TenantScoped):
    """How the business's bills look on paper (B.12): one row per business,
    created on the first save. Logo and signature are uploaded images."""

    Layout = PrintLayout
    id = uuid7_pk()
    tenant = tenant_ref()
    layout = models.TextField(
        choices=PrintLayout, default=PrintLayout.DETAILED, db_default=PrintLayout.DETAILED
    )
    logo_attachment = ref("files.Attachment", null=True)
    signature_attachment = ref("files.Attachment", null=True)
    bank_account_name = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    bank_name = models.TextField(null=True)  # noqa: DJ001
    bank_account_number = models.TextField(null=True)  # noqa: DJ001
    bank_ifsc = models.TextField(null=True)  # noqa: DJ001
    bank_branch = models.TextField(null=True)  # noqa: DJ001
    upi_id = models.TextField(null=True)  # noqa: DJ001
    default_terms = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "print_settings"
        constraints = [
            tenant_id_key("print_settings"),
            models.UniqueConstraint(fields=["tenant"], name="print_settings_tenant_id_key"),
            one_of("layout", PrintLayout.values, "print_settings_layout_check"),
            length_between("bank_account_name", 1, 200, "print_settings_bank_account_name_check"),
            length_between("bank_name", 1, 200, "print_settings_bank_name_check"),
            regex("bank_account_number", BANK_ACCOUNT_RE, "print_settings_bank_account_check"),
            regex("bank_ifsc", IFSC_RE, "print_settings_bank_ifsc_check"),
            length_between("bank_branch", 1, 200, "print_settings_bank_branch_check"),
            regex("upi_id", UPI_RE, "print_settings_upi_id_check"),
            length_between("default_terms", 1, 5000, "print_settings_default_terms_check"),
        ]
