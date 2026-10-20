import uuid

from celery import shared_task

from apps.core.tenancy import tenant_context

from .services import process_upload


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=8
)
def process_upload_task(tenant_id: str, user_id: str, attachment_id: str) -> str | None:
    """Retried with backoff while storage or the virus scanner is unreachable;
    the file stays PENDING (unusable) until it succeeds."""
    with tenant_context(tenant_id, user_id):
        return process_upload(uuid.UUID(attachment_id))
