from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from apps.core.db import (
    CITextField,
    FixedCharField,
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
from apps.tenants.models import GSTIN_RE, PAN_RE, STATE_CODE_RE


class PartyGstTreatment(models.TextChoices):
    REGISTERED = "REGISTERED"
    COMPOSITION = "COMPOSITION"
    UNREGISTERED = "UNREGISTERED"
    CONSUMER = "CONSUMER"
    SEZ = "SEZ"
    OVERSEAS = "OVERSEAS"


class Party(models.Model):
    """A customer, vendor or subcontractor."""

    GstTreatment = PartyGstTreatment
    id = uuid7_pk()
    tenant = tenant_ref()
    is_customer = models.BooleanField(default=True, db_default=True)
    is_vendor = models.BooleanField(default=False, db_default=False)  # suppliers, subcontractors
    display_name = models.TextField()
    legal_name = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    gst_treatment = models.TextField(choices=GstTreatment)
    gstin = models.CharField(max_length=15, null=True)  # noqa: DJ001
    pan = FixedCharField(max_length=10, null=True)
    state_code = FixedCharField(max_length=2, null=True)
    billing_address = models.JSONField(null=True)
    email = CITextField(null=True)
    phone = models.TextField(null=True)  # noqa: DJ001
    is_active = models.BooleanField(default=True, db_default=True)
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "parties"
        constraints = [
            tenant_id_key("parties"),
            length_between("display_name", 1, 200, "parties_display_name_check"),
            one_of("gst_treatment", PartyGstTreatment.values, "parties_gst_treatment_check"),
            regex("gstin", GSTIN_RE, "parties_gstin_check"),
            regex("pan", PAN_RE, "parties_pan_check"),
            regex("state_code", STATE_CODE_RE, "parties_state_code_check"),
            models.CheckConstraint(
                condition=Q(is_customer=True) | Q(is_vendor=True), name="parties_role_check"
            ),
            models.CheckConstraint(
                condition=Q(gst_treatment__not_in=["REGISTERED", "COMPOSITION"])
                | Q(gstin__isnull=False),
                name="parties_gstin_required_check",
            ),
            models.CheckConstraint(
                condition=Q(gstin__isnull=True) | Q(gstin__state_prefix=models.F("state_code")),
                name="parties_gstin_state_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "display_name"], name="parties_tenant_name_idx"),
            GinIndex(
                fields=["display_name"], opclasses=["gin_trgm_ops"], name="parties_name_trgm_idx"
            ),
            models.Index(
                fields=["tenant", "gstin"],
                condition=Q(gstin__isnull=False),
                name="parties_gstin_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name
