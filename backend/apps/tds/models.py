from django.db import models
from django.db.models import Q

from apps.core.db import (
    between,
    created_at,
    ref,
    regex,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)
from apps.core.managers import TenantScoped

TAN_RE = r"^[A-Z]{4}[0-9]{5}[A-Z]$"
SECTION_RE = r"^19[0-9]{1,2}[A-Z]{0,3}$"
CERTIFICATE_NUMBER_RE = r"^[A-Za-z0-9/-]{1,20}$"


class TdsCertificate(TenantScoped):
    """An income-tax TDS certificate (Form 16A) from a client, for one
    quarter. A record of the client's paper, so it may be corrected or
    deleted (audited); reconciled against the TDS deducted on our bills."""

    id = uuid7_pk()
    tenant = tenant_ref()
    party = ref("parties.Party")  # the deductor: our client
    deductor_tan = models.TextField()
    section = models.TextField(default="194C", db_default="194C")
    fy_start_year = models.SmallIntegerField()
    quarter = models.SmallIntegerField()
    certificate_number = models.TextField()
    certificate_date = models.DateField(null=True)
    amount_credited = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    tds_amount = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "tds_certificates"
        constraints = [
            tenant_id_key("tds_certificates"),
            models.UniqueConstraint(
                fields=["tenant", "deductor_tan", "certificate_number"],
                name="tds_certificates_number_key",
            ),
            regex("deductor_tan", TAN_RE, "tds_certificates_deductor_tan_check"),
            regex("section", SECTION_RE, "tds_certificates_section_check"),
            between("fy_start_year", 2000, 2100, "tds_certificates_fy_start_year_check"),
            between("quarter", 1, 4, "tds_certificates_quarter_check"),
            regex(
                "certificate_number",
                CERTIFICATE_NUMBER_RE,
                "tds_certificates_certificate_number_check",
            ),
            models.CheckConstraint(
                condition=Q(amount_credited__gte=0),
                name="tds_certificates_amount_credited_check",
            ),
            models.CheckConstraint(
                condition=Q(tds_amount__gte=0), name="tds_certificates_tds_amount_check"
            ),
            models.CheckConstraint(
                condition=Q(notes__char_length__lte=2000), name="tds_certificates_notes_check"
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "party", "fy_start_year", "quarter"],
                name="tds_certificates_party_idx",
            )
        ]

    def __str__(self) -> str:
        return f"Form 16A {self.certificate_number} ({self.fy_start_year} Q{self.quarter})"
