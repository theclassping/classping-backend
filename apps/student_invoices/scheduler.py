"""
APScheduler job definitions for student invoices.
Import and call register_jobs(scheduler) from the run_scheduler command.
"""

from io import StringIO

from django.core.management import call_command

from apps.student_invoices.services import generate_recurring_invoices


def _call_command(name):
    """Run a Django management command without stdout/stderr pickling issues."""
    call_command(
        name,
        stdout=StringIO(),
        stderr=StringIO(),
    )


def run_generate_recurring_invoices():
    """Wrapper used by APScheduler to execute the service."""
    return generate_recurring_invoices()


def run_mark_overdue_invoices():
    """Wrapper used by APScheduler to mark overdue invoices."""
    _call_command("mark_overdue_invoices")


def run_send_invoice_reminders():
    """Wrapper used by APScheduler to send invoice reminders."""
    _call_command("send_invoice_reminders")


SCHEDULED_JOBS = [
    {
        "id": "generate_recurring_invoices",
        "func": run_generate_recurring_invoices,
        "trigger": "cron",
        "hour": 1,
        "minute": 0,
    },
    {
        "id": "mark_overdue_invoices",
        "func": run_mark_overdue_invoices,
        "trigger": "cron",
        "hour": 1,
        "minute": 30,
    },
    {
        "id": "send_invoice_reminders",
        "func": run_send_invoice_reminders,
        "trigger": "cron",
        "hour": 8,
        "minute": 0,
    },
]


def register_jobs(scheduler):
    """Register all invoice-related scheduled jobs."""
    for job_kwargs in SCHEDULED_JOBS:
        scheduler.add_job(
            **job_kwargs,
            replace_existing=True,
        )