from typing import Any

from rest_framework import serializers

from . import storage
from .models import MAX_ATTACHMENT_BYTES, Attachment, AttachmentContentType, AttachmentStatus


class AttachmentSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    filename = serializers.CharField(source="original_filename")
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    status = serializers.ChoiceField(choices=AttachmentStatus.choices)
    uploaded_by = serializers.UUIDField(source="uploaded_by_id")
    created_at = serializers.DateTimeField()
    download_url = serializers.SerializerMethodField(
        help_text="A link for 5 minutes; only when the file is AVAILABLE."
    )

    def get_download_url(self, obj: Attachment) -> str | None:
        if obj.status != AttachmentStatus.AVAILABLE:
            return None
        return storage.download_url(obj.storage_key, obj.original_filename)


class UploadStartSerializer(serializers.Serializer[Any]):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.ChoiceField(
        choices=AttachmentContentType.values,
        error_messages={"invalid_choice": "Upload a PDF, JPEG, PNG or WebP file."},
    )
    size_bytes = serializers.IntegerField(
        min_value=1,
        max_value=MAX_ATTACHMENT_BYTES,
        error_messages={
            "max_value": "Files can be at most 20 MB.",
            "min_value": "The file is empty.",
        },
    )


class UploadStartedSerializer(serializers.Serializer[Any]):
    attachment = AttachmentSerializer()
    upload_url = serializers.URLField(help_text="PUT the file's bytes here within 5 minutes.")
    upload_headers = serializers.DictField(
        child=serializers.CharField(), help_text="Send exactly these headers with the PUT."
    )
    expires_in = serializers.IntegerField()
