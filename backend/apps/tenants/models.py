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
            # GST: an invoice number is at most 16 characters.
            models.CheckConstraint(
                condition=models.lookups.LessThanOrEqual(
                    CharLength("prefix") + models.F("pad_width"), 16
                ),
                name="document_series_number_length_check",
            ),
        ]
