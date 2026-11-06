"""Background work for businesses (Part B)."""

import uuid

from celery import shared_task

from . import sample


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def build_sample(user_id: str) -> str:
    """Make the user's sample business (outside any request's transaction)."""
    return str(sample.build(uuid.UUID(user_id)))
