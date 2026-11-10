"""
Periodic invoice jobs (scheduled in config/celery.py beat_schedule).

Each task only calls the existing service / management command, so the
job logic is unchanged from the APScheduler version.
"""

from io import StringIO

from celery import shared_task
from django.core.management import call_command

from apps.student_invoices.services import generate_recurring_invoices


def _call_command(name):
    """Run a management command without writing to the worker's stdout."""
    call_command(name, stdout=StringIO(), stderr=StringIO())


@shared_task
def generate_recurring_invoices_task():
    return generate_recurring_invoices()


@shared_task
def mark_overdue_invoices_task():
    _call_command("mark_overdue_invoices")


@shared_task
def send_invoice_reminders_task():
    _call_command("send_invoice_reminders")
