from django.core.management.base import BaseCommand

from apps.student_invoices.services import generate_recurring_invoices


class Command(BaseCommand):
    help = "Generate recurring invoices for active fee types. Run via cron/job scheduler."

    def handle(self, *args, **options):
        created_count = generate_recurring_invoices()

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully generated {created_count} recurring invoice(s)."
            )
        )