"""
Import a DANA settlement file (same as Admin web -> Settlements).

    python manage.py import_dana_settlement MERCHANT_SETTLEMENT_..._20261119.csv --dry-run
    python manage.py import_dana_settlement MERCHANT_SETTLEMENT_..._20261119.csv

--dry-run only prints what would happen. Without it, matching paid online
payments are settled (pending -> available) and mismatches flagged.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import CodedAPIException
from apps.payment_gateway import settlement


class Command(BaseCommand):
    help = "Import a DANA settlement file (CSV)."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--dry-run", action="store_true", help="Show the result without changing anything.")

    def handle(self, *args, path, dry_run, **options):
        try:
            with open(path, "rb") as handle:
                content = handle.read()
        except OSError as error:
            raise CommandError(str(error))
        name = os.path.basename(path)
        try:
            preview = settlement.preview_settlement_file("dana", name, content)
            for planned in preview.lines:
                line = planned.line
                self.stdout.write("{:>4} {:<16} {:<36} {:>14} {:<16} {}".format(
                    line.line_no, line.provider_type, line.provider_trx_id or line.original_trx_id,
                    str(line.amount), planned.result, planned.note,
                ))
            summary = "{} lines: {} to settle ({}), {} to review, {} unmatched".format(
                len(preview.lines), preview.settled_count, preview.settled_total,
                preview.review_count, preview.unmatched_count,
            )
            if dry_run:
                self.stdout.write("DRY RUN, nothing changed. " + summary)
                return
            imported = settlement.import_settlement_file(None, "dana", name, content)
        except CodedAPIException as error:
            raise CommandError(error.message)
        self.stdout.write(self.style.SUCCESS("Imported settlement file #{}: {}".format(imported.pk, summary)))
