from django.db import models
from django.db.models import Q

from apps.core.db import (
    between,
    created_at,
    length_between,
    one_of,
    ref,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)
from apps.core.managers import TenantScoped

TEMPLATE_TYPES = ["QUOTATION", "PROFORMA", "TAX_INVOICE", "BILL_OF_SUPPLY"]


class DocumentTemplate(TenantScoped):
    """A saved quote / bill to start new drafts from (db/schema.sql §3).
    Lines are copied values; drafts made from it follow the normal draft rules."""

    id = uuid7_pk()
    tenant = tenant_ref()
    name = models.TextField()
    doc_type = models.TextField()
    valid_days = models.SmallIntegerField(null=True)
    notes = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    terms = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    lines = models.JSONField()
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "document_templates"
        constraints = [
            tenant_id_key("document_templates"),
            models.UniqueConstraint(
                fields=["tenant", "name"], name="document_templates_tenant_id_name_key"
            ),
            length_between("name", 1, 100, "document_templates_name_check"),
            one_of("doc_type", TEMPLATE_TYPES, "document_templates_doc_type_check"),
            between("valid_days", 1, 365, "document_templates_valid_days_check"),
            models.CheckConstraint(
                condition=Q(notes__char_length__lte=5000), name="document_templates_notes_check"
            ),
            models.CheckConstraint(
                condition=Q(terms__char_length__lte=5000), name="document_templates_terms_check"
            ),
        ]

    def __str__(self) -> str:
        return self.name
