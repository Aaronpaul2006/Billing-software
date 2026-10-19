"""Celery app: background work (PDFs now; email, exports, e-invoicing later).

Every task receives tenant_id / user_id explicitly and runs inside
tenant_context(): workers never have an ambient tenant.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("billing")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
