from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.files import storage

from .models import DiaryEntry, DiaryPhoto, Weather


class PhotoInSerializer(serializers.Serializer[Any]):
    attachment_id = serializers.UUIDField(help_text="An uploaded image that passed the check")
    caption = serializers.CharField(max_length=200, required=False, allow_blank=True)


class PhotosInSerializer(serializers.Serializer[Any]):
    photos = PhotoInSerializer(many=True)


class EntryWriteSerializer(serializers.Serializer[Any]):
    entry_date = serializers.DateField()
    weather = serializers.ChoiceField(choices=Weather.choices, required=False, allow_null=True)
    workers = serializers.IntegerField(
        min_value=0, max_value=10000, required=False, allow_null=True
    )
    work_done = serializers.CharField(max_length=4000)
    hold_ups = serializers.CharField(
        max_length=2000, required=False, allow_null=True, allow_blank=True
    )
    photos = PhotoInSerializer(many=True, required=False)


class EntryUpdateSerializer(serializers.Serializer[Any]):
    weather = serializers.ChoiceField(choices=Weather.choices, required=False, allow_null=True)
    workers = serializers.IntegerField(
        min_value=0, max_value=10000, required=False, allow_null=True
    )
    work_done = serializers.CharField(max_length=4000, required=False)
    hold_ups = serializers.CharField(
        max_length=2000, required=False, allow_null=True, allow_blank=True
    )


class PhotoSerializer(serializers.ModelSerializer[DiaryPhoto]):
    attachment_id = serializers.UUIDField()
    url = serializers.SerializerMethodField(help_text="To show it; valid for a few minutes")

    class Meta:
        model = DiaryPhoto
        fields = ("id", "attachment_id", "caption", "url", "created_at")
        read_only_fields = fields

    def get_url(self, obj: DiaryPhoto) -> str:
        a = obj.attachment
        return storage.download_url(a.storage_key, a.original_filename)


class EntrySerializer(serializers.ModelSerializer[DiaryEntry]):
    project_id = serializers.UUIDField()
    written_by = serializers.CharField(source="created_by.full_name", read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = DiaryEntry
        fields = (
            "id",
            "version",
            "project_id",
            "entry_date",
            "weather",
            "workers",
            "work_done",
            "hold_ups",
            "photos",
            "written_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(PhotoSerializer(many=True))
    def get_photos(self, obj: DiaryEntry) -> Any:
        photos = obj.photos.select_related("attachment").order_by("sort_order", "created_at")
        return PhotoSerializer(photos, many=True).data


class DiaryQuerySerializer(serializers.Serializer[Any]):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
