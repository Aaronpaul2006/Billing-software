"""GSTR-2B as uploaded (Part B). The tables are written in SQL (db/schema.sql,
the same text as the migration); these models only read and write them."""

from django.db import models

from apps.core.db import created_at, ref, tenant_ref, uuid7_pk
from apps.core.managers import TenantScoped


class Gstr2bReturn(TenantScoped):
    """One registration's GSTR-2B for one month."""

    id = uuid7_pk()
    tenant = tenant_ref()
    gst_registration = ref("tenants.GstRegistration")
    period = models.DateField()
    generated_on = models.DateField(null=True)
    file_name = models.TextField()
    doc_count = models.IntegerField()
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()

    class Meta:
        db_table = "gstr2b_returns"


class Gstr2bLine(TenantScoped):
    """One document in the GSTR-2B, as the portal shows it."""

    id = uuid7_pk()
    tenant = tenant_ref()
    gst_return = ref("gstr2b.Gstr2bReturn", db_column="return_id", related_name="lines")
    section = models.TextField()
    doc_type = models.TextField()
    supplier_gstin = models.CharField(max_length=15)
    supplier_name = models.TextField(default="", db_default="")
    doc_number = models.TextField()
    original_number = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    doc_date = models.DateField()
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    cess = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    place_of_supply = models.CharField(max_length=2, null=True)  # noqa: DJ001
    reverse_charge = models.BooleanField(default=False, db_default=False)
    itc_available = models.BooleanField(default=True, db_default=True)
    itc_reason = models.TextField(null=True)  # noqa: DJ001

    class Meta:
        db_table = "gstr2b_lines"
