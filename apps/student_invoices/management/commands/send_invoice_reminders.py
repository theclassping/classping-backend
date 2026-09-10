from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.student_invoices.models import StudentInvoice


class Command(BaseCommand):
    help = "Send reminders for invoices due in 5 days. Run via cron/job scheduler."

    def handle(self, *args, **options):
        reminder_date = timezone.now().date() + timedelta(days=5)

        invoices = StudentInvoice.objects.filter(
            due_date=reminder_date,
            status__in=[
                StudentInvoice.Status.UNPAID,
                StudentInvoice.Status.PAYMENT_SUBMITTED,
            ],
        ).select_related(
            "class_student__student",
            "class_student__class_obj",
            "fee_type",
        )

        count = 0
        for invoice in invoices:
            self._send_reminder(invoice)
            count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {count} reminder(s) for invoices due on {reminder_date}."
            )
        )

    def _send_reminder(self, invoice: StudentInvoice):
        """
        MVP placeholder: log reminder to stdout.
        Replace with email/push notification integration when ready.
        """
        student = invoice.class_student.student
        self.stdout.write(
            f"REMINDER: Invoice {invoice.invoice_no} "
            f"for {student.first_name} {student.last_name} "
            f"due on {invoice.due_date} - amount {invoice.total_amount} {invoice.currency}"
        )