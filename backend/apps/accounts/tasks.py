import uuid

from celery import shared_task

from apps.core.tenancy import tenant_context

from .email_invitations import send_invitation_email
from .emails import Kind, send


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=5
)
def send_account_email(kind: str, user_id: str, extra: dict[str, str] | None = None) -> bool:
    """Retried with backoff while the mail server is unreachable (SMTP errors are OSErrors)."""
    return send(Kind(kind), uuid.UUID(user_id), extra)


@shared_task(  # type: ignore[untyped-decorator]  # celery has no type hints
    acks_late=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=5
)
def send_invitation_email_task(tenant_id: str, invitation_id: str) -> bool:
    """The invitation email to someone with no account yet (built in the tenant's context)."""
    with tenant_context(tenant_id):
        return send_invitation_email(uuid.UUID(invitation_id))
