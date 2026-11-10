"""
Create MediaObject rows for files attached before storage tracking existed.

Safe to re-run: keys already tracked as attached are skipped. Legacy keys
take their branch from the record (first branch for a school logo or a
guardian with children in several branches).

    python manage.py backfill_media_objects --dry-run
    python manage.py backfill_media_objects --fetch-missing-sizes
"""
from collections import defaultdict

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.uploads.models import MediaObject
from apps.uploads.references import MEDIA_MODELS
from apps.uploads.services.media import MediaService
from apps.uploads.tracking import location_for, metadata_value, record_attached
from apps.uploads.utils import MediaFieldMixin


class Command(BaseCommand):
    help = "Track storage usage for media attached before MediaObject existed."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report totals without writing.")
        parser.add_argument(
            "--fetch-missing-sizes",
            action="store_true",
            help="Ask storage for the size of files whose metadata has none (one request each).",
        )

    def handle(self, *args, dry_run=False, fetch_missing_sizes=False, **options):
        already = MediaObject.objects.filter(status=MediaObject.Status.ATTACHED)
        if fetch_missing_sizes:
            # Revisit rows an earlier run tracked without a size.
            already = already.exclude(size_bytes=0)
        tracked = set(already.values_list("file_key", flat=True))
        totals = defaultdict(lambda: [0, 0])  # branch_id -> [files, bytes]
        created = skipped = missing_size = 0

        with transaction.atomic():
            for label in MEDIA_MODELS:
                model = apps.get_model(label)
                rows = model._base_manager.exclude(image_data=None).iterator(chunk_size=500)
                for instance in rows:
                    image_data = MediaFieldMixin._parse_media_data(instance.image_data)
                    if not isinstance(image_data, dict):
                        continue
                    key = image_data.get("id") or image_data.get("object_key")
                    if not key or key in tracked:
                        skipped += bool(key)
                        continue
                    tracked.add(key)

                    size = metadata_value(image_data, "size")
                    if not size and fetch_missing_sizes:
                        size = MediaService._get_file_size(key)
                        image_data = {**image_data, "size": size}
                    if not size:
                        missing_size += 1

                    location = location_for(instance, key)
                    branch_total = totals[location.branch_id if location else None]
                    branch_total[0] += 1
                    branch_total[1] += int(size or 0)
                    created += 1
                    if not dry_run:
                        record_attached(instance, key, image_data)

            if dry_run:
                transaction.set_rollback(True)

        for branch_id, (files, size) in sorted(totals.items(), key=lambda item: (item[0] is None, item[0] or 0)):
            name = f"branch {branch_id}" if branch_id else "no branch"
            self.stdout.write(f"{name}: {files} file(s), {size} bytes")
        verb = "Would track" if dry_run else "Tracked"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} file(s); {skipped} already tracked; {missing_size} without a known size."
        ))
        if missing_size and not fetch_missing_sizes:
            self.stdout.write("Re-run with --fetch-missing-sizes to read those sizes from storage.")
