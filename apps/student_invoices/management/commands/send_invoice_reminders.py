from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from apps.mailer.services import Mailer
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
            if self._send_reminder(invoice):
                count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {count} reminder(s) for invoices due on {reminder_date}."
            )
        )

    def _send_reminder(self, invoice: StudentInvoice):
        student = invoice.class_student.student
        relation = (
            student.student_guardians
            .filter(is_primary=True)
            .select_related("guardian__user")
            .first()
        )
        guardian = relation.guardian if relation else None
        to_email = (guardian.email if guardian else None) or (
            guardian.user.email if guardian and guardian.user else None
        )

        if not to_email:
            message = (
                f"REMINDER SKIPPED: Invoice {invoice.invoice_no} "
                "has no primary guardian email."
            )
            self.stdout.write(message)
            self.stderr.write(
                self.style.WARNING(
                    message
                )
            )
            return False

        redis_client = self._redis()
        reminder_key = f"classping:invoice-reminder:{invoice.pk}:{invoice.due_date.isoformat()}"
        if redis_client and not redis_client.set(reminder_key, "sent", ex=90 * 86400, nx=True):
            return False

        try:
            Mailer().send_template(
                to_email=to_email,
                to_name=guardian.name,
                template_id=settings.MAILJET_TEMPLATES["invoice_reminder"],
                variables={
                    "student_name": student.full_name(),
                    "invoice_no": invoice.invoice_no,
                    "due_date": invoice.due_date.strftime("%A, %d %B %Y"),
                    "amount": str(invoice.total_amount),
                    "currency": invoice.currency,
                },
                subject=f"Invoice reminder for {student.full_name()}",
            )
        except Exception as exc:
            if redis_client:
                redis_client.delete(reminder_key)
            self.stderr.write(
                self.style.ERROR(
                    f"Failed reminder for {invoice.invoice_no} to {to_email}: {exc}"
                )
            )
            return False

        self.stdout.write(
            f"REMINDER SENT: Invoice {invoice.invoice_no} "
            f"for {student.full_name()} to {to_email}"
        )
        return True

    @staticmethod
    def _redis():
        redis_url = getattr(settings, "REDIS_URL", "")
        if not redis_url:
            return None
        try:
            import redis
            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            return None
