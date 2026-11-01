from celery import shared_task

from . import services


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def send_due_reminders() -> int:
    """Daily (Celery beat): each active tenant's due payment reminders."""
    return services.send_due_reminders()
