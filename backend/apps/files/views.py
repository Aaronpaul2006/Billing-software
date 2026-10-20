"""Upload endpoints (docs/02-api-design.md §7). Thin: validate, call a service, respond."""

import uuid

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import ActionAPIView
from apps.core.idempotency import idempotent_if_keyed

from . import services
from .serializers import AttachmentSerializer, UploadStartedSerializer, UploadStartSerializer


class AttachmentListView(ActionAPIView):
    """Start an upload: a PENDING attachment and a presigned PUT (5 minutes) that
    accepts only the declared type and size. Then PUT the bytes and call complete."""

    write_action = services.UPLOAD

    @extend_schema(
        request=UploadStartSerializer, responses={201: UploadStartedSerializer}, tags=["files"]
    )
    @idempotent_if_keyed
    def post(self, request: Request) -> Response:
        data = UploadStartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        attachment, url, headers = services.start_upload(
            self.principal,
            filename=v["filename"],
            content_type=v["content_type"],
            size_bytes=v["size_bytes"],
        )
        body = {
            "attachment": AttachmentSerializer(attachment).data,
            "upload_url": url,
            "upload_headers": headers,
            "expires_in": settings.UPLOAD_URL_TTL,
        }
        return Response(body, status=201)


class AttachmentDetailView(ActionAPIView):
    """An attachment, with a 5-minute download link once it is AVAILABLE."""

    write_action = services.UPLOAD

    @extend_schema(responses={200: AttachmentSerializer}, tags=["files"])
    def get(self, request: Request, attachment_id: uuid.UUID) -> Response:
        attachment = services.get_attachment(self.principal, attachment_id)
        response = Response(AttachmentSerializer(attachment).data)
        response["Cache-Control"] = "no-store"  # the download link is short-lived
        return response


class AttachmentCompleteView(ActionAPIView):
    """After the PUT (uploader only): checks size, type and magic bytes, then a
    background scan makes it AVAILABLE or QUARANTINED. Poll the attachment."""

    write_action = services.UPLOAD

    @extend_schema(request=None, responses={202: AttachmentSerializer}, tags=["files"])
    def post(self, request: Request, attachment_id: uuid.UUID) -> Response:
        attachment = services.complete_upload(self.principal, attachment_id)
        return Response(AttachmentSerializer(attachment).data, status=202)
