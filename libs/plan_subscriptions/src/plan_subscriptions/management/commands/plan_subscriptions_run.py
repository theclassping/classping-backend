from django.core.management.base import BaseCommand

from plan_subscriptions import services


class Command(BaseCommand):
    help = "Run the subscription jobs (statuses, due invoices, reminders). For hosts without Celery: run hourly."

    def handle(self, *args, **options):
        self.stdout.write(str(services.run_all()))
