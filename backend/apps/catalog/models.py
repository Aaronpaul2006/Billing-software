from django.db import models

from apps.core.db import (
    between,
    created_at,
    length_between,
    non_negative,
    ref,
    regex,
    tenant_id_key,
    tenant_ref,
    updated_at,
    uuid7_pk,
)
from apps.core.managers import TenantScoped
from apps.projects.models import SAC_HSN_RE


class CatalogItem(TenantScoped):
    """A reusable item with a default rate."""

    id = uuid7_pk()
    tenant = tenant_ref()
    name = models.TextField()
    description = models.TextField(null=True)  # noqa: DJ001 - mirrors schema
    unit = models.TextField(null=True)  # noqa: DJ001
    sac_hsn = models.TextField(null=True)  # noqa: DJ001
    default_rate = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18, db_default=18)
    is_active = models.BooleanField(default=True, db_default=True)
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "catalog_items"
        constraints = [
            tenant_id_key("catalog_items"),
            length_between("name", 1, 200, "catalog_items_name_check"),
            regex("sac_hsn", SAC_HSN_RE, "catalog_items_sac_hsn_check"),
            non_negative("default_rate", "catalog_items_default_rate_check"),
            between("gst_rate", 0, 50, "catalog_items_gst_rate_check"),
        ]

    def __str__(self) -> str:
        return self.name


class CatalogItemVariant(TenantScoped):
    """A variant of a catalog item (db/schema.sql §3), e.g. Brand: UltraTech.
    Its rate is the item's default rate plus `rate_delta` (may be negative)."""

    id = uuid7_pk()
    tenant = tenant_ref()
    catalog_item = ref("catalog.CatalogItem", related_name="variants")
    attribute = models.TextField()
    value = models.TextField()
    rate_delta = models.DecimalField(max_digits=14, decimal_places=2, default=0, db_default=0)
    is_active = models.BooleanField(default=True, db_default=True)
    version = models.IntegerField(default=1, db_default=1)
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "catalog_item_variants"
        constraints = [
            tenant_id_key("catalog_item_variants"),
            models.UniqueConstraint(
                fields=["tenant", "catalog_item", "id"],
                name="catalog_item_variants_tenant_id_catalog_item_id_id_key",
            ),
            models.UniqueConstraint(
                fields=["tenant", "catalog_item", "attribute", "value"],
                name="catalog_item_variants_tenant_id_catalog_item_id_attribute_v_key",
            ),
            length_between("attribute", 1, 50, "catalog_item_variants_attribute_check"),
            length_between("value", 1, 100, "catalog_item_variants_value_check"),
        ]

    def __str__(self) -> str:
        return f"{self.attribute}: {self.value}"
