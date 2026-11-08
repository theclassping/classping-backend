"""
Celery app: background tasks and periodic jobs (replaces APScheduler).

Runs in the existing `scheduler` container as one process (worker + beat):
    celery -A config worker -B
Run exactly ONE instance of that container, otherwise periodic jobs run twice.
Broker: Redis from REDIS_URL, database /1 (see CELERY_BROKER_URL in settings).
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("classping")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Periodic jobs. Hours follow CELERY_TIMEZONE (= TIME_ZONE).
app.conf.beat_schedule = {
    "generate_recurring_invoices": {
        "task": "apps.student_invoices.tasks.generate_recurring_invoices_task",
        "schedule": crontab(hour=1, minute=0),
    },
    "mark_overdue_invoices": {
        "task": "apps.student_invoices.tasks.mark_overdue_invoices_task",
        "schedule": crontab(hour=1, minute=30),
    },
    "send_invoice_reminders": {
        "task": "apps.student_invoices.tasks.send_invoice_reminders_task",
        "schedule": crontab(hour=8, minute=0),
    },
    "reconcile_gateway_settlements": {
        "task": "apps.payment_gateway.tasks.reconcile_settlements_task",
        "schedule": crontab(minute=15),  # hourly
    },
    "poll_processing_withdrawals": {
        "task": "apps.wallets.tasks.poll_processing_withdrawals_task",
        "schedule": crontab(minute="*/5"),
    },
}
