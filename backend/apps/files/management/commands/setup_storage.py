from typing import Any

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.files import storage


class Command(BaseCommand):
    help = (
        "Create the bucket if it is missing and allow browser uploads from "
        "S3_CORS_ORIGINS (presigned PUT straight to storage). Safe to run again."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        client = storage.internal_client()
        bucket = settings.S3_BUCKET
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            client.create_bucket(Bucket=bucket)
            self.stdout.write(f"Created bucket {bucket}")
        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": list(settings.S3_CORS_ORIGINS),
                        "AllowedMethods": ["PUT", "GET"],
                        "AllowedHeaders": ["content-type"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )
        self.stdout.write(
            self.style.SUCCESS(f"Bucket {bucket}: uploads allowed from {settings.S3_CORS_ORIGINS}")
        )
