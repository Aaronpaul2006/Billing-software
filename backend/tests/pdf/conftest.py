from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from django.test import override_settings
from moto import mock_aws

from apps.files import storage


@pytest.fixture
def s3() -> Iterator[Any]:
    with (
        mock_aws(),
        override_settings(
            S3_ENDPOINT_URL=None,
            S3_PUBLIC_ENDPOINT_URL=None,
            S3_REGION="us-east-1",
            S3_BUCKET="test-bucket",
        ),
    ):
        storage._client.cache_clear()
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client
    storage._client.cache_clear()
