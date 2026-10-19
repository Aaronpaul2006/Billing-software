import uuid

from celery import shared_task

from apps.core.tenancy import tenant_context

from .services.pdfs import store_pdf


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5
)
def render_document_pdf(tenant_id: str, user_id: str, document_id: str) -> str | None:
    """Retried with backoff on failure (e.g. storage briefly unreachable)."""
    with tenant_context(tenant_id, user_id):
        attachment_id = store_pdf(uuid.UUID(document_id), uuid.UUID(user_id))
    return str(attachment_id) if attachment_id else None
