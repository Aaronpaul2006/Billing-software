from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from apps.core.db import (
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
from apps.tenants.models import STATE_CODE_RE

SAC_HSN_RE = r"^[0-9]{4,8}$"


class ProjectStatus(models.TextChoices):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Project(TenantScoped):
    Status = ProjectStatus
    id = uuid7_pk()
    tenant = tenant_ref()
    code = models.TextField()
    name = models.TextField()
    client_party = ref("parties.Party")
    gst_registration = ref("tenants.GstRegistration")  # which of our registrations bills it
    site_address = models.JSONField(null=True)
    # Works on immovable property: the GST place of supply is where the
    # property is (IGST Act s.12(3)), so this decides CGST+SGST vs IGST.
    site_state_code = FixedCharField(max_length=2)
    contract_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    retention_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0, db_default=0)
    income_tax_tds_pct = models.DecimalField(  # e.g. s.194C
        max_digits=5, decimal_places=2, default=0, db_default=0
    )
    gst_tds_applicable = models.BooleanField(default=False, db_default=False)  # CGST s.51
    mobilisation_advance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, db_default=0
    )
    advance_recovery_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, db_default=0
    )
    status = models.TextField(
        choices=Status, default=ProjectStatus.ACTIVE, db_default=ProjectStatus.ACTIVE
    )
    start_date = models.DateField(null=True)
    end_date = models.DateField(null=True)
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "projects"
        constraints = [
            tenant_id_key("projects"),
            models.UniqueConstraint(fields=["tenant", "code"], name="projects_tenant_id_code_key"),
            regex("code", r"^[A-Za-z0-9_-]{1,30}$", "projects_code_check"),
            length_between("name", 1, 200, "projects_name_check"),
            regex("site_state_code", STATE_CODE_RE, "projects_site_state_code_check"),
            non_negative("contract_value", "projects_contract_value_check"),
            between("retention_pct", 0, 100, "projects_retention_pct_check"),
            between("income_tax_tds_pct", 0, 100, "projects_income_tax_tds_pct_check"),
            non_negative("mobilisation_advance", "projects_mobilisation_advance_check"),
            between("advance_recovery_pct", 0, 100, "projects_advance_recovery_pct_check"),
            one_of("status", ProjectStatus.values, "projects_status_check"),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True)
                | Q(start_date__isnull=True)
                | Q(end_date__gte=models.F("start_date")),
                name="projects_dates_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "client_party"], name="projects_client_idx"),
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="projects_name_trgm_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class BoqItem(TenantScoped):
    """Bill of Quantities line: the priced items RA bills bill progress against."""

    id = uuid7_pk()
    tenant = tenant_ref()
    project = ref("projects.Project", related_name="boq_items")
    item_code = models.TextField()  # e.g. "2.1.3"
    description = models.TextField()
    unit = models.TextField()  # cum, sqm, kg, nos
    sac_hsn = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    contract_qty = models.DecimalField(max_digits=14, decimal_places=3)
    rate = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18, db_default=18)
    is_variation = models.BooleanField(default=False, db_default=False)  # extra item / change order
    sort_order = models.IntegerField(default=0, db_default=0)
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "boq_items"
        constraints = [
            tenant_id_key("boq_items"),
            models.UniqueConstraint(
                fields=["tenant", "project", "item_code"],
                name="boq_items_tenant_id_project_id_item_code_key",
            ),
            length_between("item_code", 1, 30, "boq_items_item_code_check"),
            length_between("description", 1, 2000, "boq_items_description_check"),
            length_between("unit", 1, 20, "boq_items_unit_check"),
            regex("sac_hsn", SAC_HSN_RE, "boq_items_sac_hsn_check"),
            non_negative("contract_qty", "boq_items_contract_qty_check"),
            non_negative("rate", "boq_items_rate_check"),
            between("gst_rate", 0, 50, "boq_items_gst_rate_check"),
        ]
