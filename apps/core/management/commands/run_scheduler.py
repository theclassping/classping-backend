import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore, register_events
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from apps.student_invoices.scheduler import register_jobs


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs APScheduler background jobs for invoice generation, reminders, and overdue marking."

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(
            timezone=settings.TIME_ZONE,
            executors={
                "default": ThreadPoolExecutor(max_workers=10),
            },
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )

        scheduler.add_jobstore(DjangoJobStore(), "default")
        register_events(scheduler)
        register_jobs(scheduler)

        self.stdout.write(
            self.style.SUCCESS("Scheduler started. Press CTRL+C to exit.")
        )

        try:
            scheduler.start()
        except KeyboardInterrupt:
            if scheduler.running:
                scheduler.shutdown()
            self.stdout.write(
                self.style.SUCCESS("Scheduler stopped.")
            )
