"""Notifications sent after the event is saved, in the business's own context
(a portal session or another tenant's session cannot write them)."""

import logging
import uuid

from celery import shared_task

from apps.accounts.models import Membership
from apps.core.tenancy import tenant_context
from apps.reminders.services import active_tenants, tenant_today

from . import services

log = logging.getLogger(__name__)


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def quotation_response(tenant_id: str, doc_id: str, accepted: bool) -> int:
    return services.quotation_response(uuid.UUID(tenant_id), uuid.UUID(doc_id), accepted)


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def member_joined(tenant_id: str, user_id: str) -> int:
    tid, uid = uuid.UUID(tenant_id), uuid.UUID(user_id)
    with tenant_context(tid):
        m = (
            Membership.objects.filter(user_id=uid, status="ACTIVE", party_id__isnull=True)
            .select_related("user")
            .first()
        )
        if m is None:  # a client's portal login, or already gone: nothing to tell
            return 0
        return services.member_joined(tid, uid, m.user.full_name, m.role)


@shared_task  # type: ignore[untyped-decorator]  # celery has no type hints
def daily() -> int:
    """Daily (Celery beat): each active tenant, on its own "today"."""
    sent = 0
    for tenant_id, time_zone in active_tenants():
        try:
            sent += services.daily(tenant_id, tenant_today(time_zone))
        except Exception:
            log.exception("daily notifications failed for tenant %s", tenant_id)
    return sent
