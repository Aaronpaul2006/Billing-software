"""Site diary (Part B). The tables are written in SQL (db/schema.sql, the same
text as the migration); these models only read and write them."""

from django.db import models

from apps.core.db import created_at, ref, tenant_ref, updated_at, uuid7_pk
from apps.core.managers import TenantScoped


class Weather(models.TextChoices):
    SUNNY = "SUNNY"
    CLOUDY = "CLOUDY"
    RAIN = "RAIN"
    HEAVY_RAIN = "HEAVY_RAIN"


class DiaryEntry(TenantScoped):
    """One project's day on site."""

    id = uuid7_pk()
    tenant = tenant_ref()
    project = ref("projects.Project")
    entry_date = models.DateField()
    weather = models.TextField(choices=Weather, null=True)  # noqa: DJ001 - mirrors schema
    workers = models.IntegerField(null=True)
    work_done = models.TextField()
    hold_ups = models.TextField(null=True)  # noqa: DJ001
    version = models.IntegerField(default=1, db_default=1)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()
    updated_at = updated_at()

    class Meta:
        db_table = "site_diary_entries"


class DiaryPhoto(TenantScoped):
    """A photo from that day (an image attachment), with a caption."""

    id = uuid7_pk()
    tenant = tenant_ref()
    entry = ref("diary.DiaryEntry", related_name="photos", on_delete=models.DO_NOTHING)
    attachment = ref("files.Attachment")
    caption = models.TextField(null=True)  # noqa: DJ001
    sort_order = models.IntegerField(default=0, db_default=0)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()

    class Meta:
        db_table = "site_diary_photos"


class DocumentPhoto(TenantScoped):
    """A diary photo chosen to go with a bill as proof of work."""

    id = uuid7_pk()
    tenant = tenant_ref()
    # The database removes these with their bill or photo (ON DELETE CASCADE).
    document = ref("documents.Document", on_delete=models.DO_NOTHING)
    diary_photo = ref("diary.DiaryPhoto", on_delete=models.DO_NOTHING)
    sort_order = models.IntegerField(default=0, db_default=0)
    created_by = ref("accounts.User", db_column="created_by")
    created_at = created_at()

    class Meta:
        db_table = "document_photos"
