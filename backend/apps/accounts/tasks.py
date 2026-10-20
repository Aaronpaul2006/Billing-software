import uuid

from celery import shared_task

from .emails import Kind, send


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=5
)
def send_account_email(kind: str, user_id: str) -> bool:
    """Retried with backoff while the mail server is unreachable (SMTP errors are OSErrors)."""
    return send(Kind(kind), uuid.UUID(user_id))
