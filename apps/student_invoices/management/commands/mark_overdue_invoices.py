from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.student_invoices.models import StudentInvoice


class Command(BaseCommand):
    help = "Mark unpaid invoices as overdue when past their due date. Run via cron/job scheduler."

    def handle(self, *args, **options):
        today = timezone.now().date()

        invoices = StudentInvoice.objects.filter(
            due_date__lt=today,
            status=StudentInvoice.Status.UNPAID,
        )

        updated_count = invoices.update(
            status=StudentInvoice.Status.OVERDUE,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Marked {updated_count} invoice(s) as overdue."
            )
        )