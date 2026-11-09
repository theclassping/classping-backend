"""
Delete upload objects nobody attached, and (with --reconcile) bring
media_objects back in line with what each branch folder really holds.

    python manage.py cleanup_orphaned_uploads
    python manage.py cleanup_orphaned_uploads --reconcile --dry-run
    python manage.py cleanup_orphaned_uploads --reconcile --branch 3
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.classes.models import Class
from apps.schools.models import Branch
from apps.uploads.models import MediaObject
from apps.uploads.paths import parse_media_key
from apps.uploads.references import is_media_referenced
from apps.uploads.services.media import MediaService
from apps.uploads.storage import get_storage
from apps.uploads.tracking import record_deleted

logger = logging.getLogger(__name__)

# Presigned URLs live at most UPLOAD_METADATA_TTL; wait a little longer so
# an upload finishing right at expiry can still be attached.
PENDING_GRACE = timedelta(minutes=10)
COUNTED = (MediaObject.Status.PENDING, MediaObject.Status.ATTACHED)
LOOKUP_BATCH = 1000


def _grace_cutoff():
    return timezone.now() - timedelta(seconds=settings.UPLOAD_METADATA_TTL) - PENDING_GRACE


class Command(BaseCommand):
    help = "Delete expired, incomplete upload objects from storage; --reconcile also checks branch folders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reconcile",
            action="store_true",
            help="List each branch_{id}/ folder and fix media_objects to match it (one listing per branch).",
        )
        parser.add_argument("--branch", type=int, help="Reconcile only this branch id.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="With --reconcile: report what would change without deleting or writing anything.",
        )

    def handle(self, *args, reconcile=False, branch=None, dry_run=False, **options):
        if (branch or dry_run) and not reconcile:
            raise CommandError("--branch and --dry-run only apply with --reconcile.")

        if not dry_run:
            deleted = self._cleanup_redis_pending()
            deleted += self._cleanup_tracked_pending()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} orphaned upload(s)."))

        if reconcile:
            self._reconcile(branch, dry_run)

    # -- pending uploads ----------------------------------------------------

    def _cleanup_redis_pending(self):
        client = MediaService._redis()
        if not client:
            self.stdout.write("Redis is not configured; skipping Redis pending uploads.")
            return 0

        keys = client.zrangebyscore(
            MediaService._pending_uploads_key(), 0, timezone.now().timestamp()
        )
        storage = get_storage()
        deleted = 0
        for file_key in keys:
            if is_media_referenced(file_key):
                MediaService.mark_upload_attached(file_key)
            else:
                storage.delete_object(file_key)
                record_deleted(file_key)
                deleted += 1
                client.delete(MediaService._upload_cache_key(file_key))
                client.zrem(MediaService._pending_uploads_key(), file_key)
        return deleted

    def _cleanup_tracked_pending(self):
        """Expire MediaObject rows still pending after their URL lapsed."""
        keys = list(
            MediaObject.objects.filter(status=MediaObject.Status.PENDING, created_at__lt=_grace_cutoff())
            .values_list("file_key", flat=True)
        )
        if not keys:
            return 0

        storage = get_storage()
        deleted = 0
        for file_key in keys:
            if is_media_referenced(file_key):
                # Attached by a path that skipped tracking; count it as attached.
                MediaObject.objects.filter(file_key=file_key).update(
                    status=MediaObject.Status.ATTACHED, attached_at=timezone.now(),
                )
                continue
            storage.delete_object(file_key)
            record_deleted(file_key)
            deleted += 1
        return deleted

    # -- reconciliation -----------------------------------------------------

    def _reconcile(self, branch_id, dry_run):
        branches = Branch.objects.order_by("pk")
        if branch_id is not None:
            branches = branches.filter(pk=branch_id)
            if not branches.exists():
                raise CommandError(f"Branch {branch_id} does not exist.")

        storage = get_storage()
        totals = {"adopted": 0, "deleted": 0, "resized": 0, "missing": 0}
        for branch in branches:
            counts = self._reconcile_branch(storage, branch.pk, dry_run)
            for name, value in counts.items():
                totals[name] += value
            if any(counts.values()):
                self.stdout.write(
                    f"branch {branch.pk}: {counts['adopted']} adopted, {counts['deleted']} deleted, "
                    f"{counts['resized']} resized, {counts['missing']} missing"
                )

        prefix = "Would reconcile" if dry_run else "Reconciled"
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}: {totals['adopted']} untracked file(s) adopted, {totals['deleted']} orphan(s) deleted, "
            f"{totals['resized']} size(s) corrected, {totals['missing']} tracked file(s) missing from storage."
        ))

    def _reconcile_branch(self, storage, branch_id, dry_run):
        prefix = f"branch_{branch_id}/"
        objects = list(storage.list_objects(prefix))
        rows = {}
        keys = [item.key for item in objects]
        for start in range(0, len(keys), LOOKUP_BATCH):
            for row in MediaObject.objects.filter(file_key__in=keys[start:start + LOOKUP_BATCH]):
                rows[row.file_key] = row

        counts = {"adopted": 0, "deleted": 0, "resized": 0, "missing": 0}
        cutoff = _grace_cutoff()
        for item in objects:
            row = rows.get(item.key)
            if row is not None and row.status in COUNTED:
                if row.size_bytes != item.size:
                    counts["resized"] += 1
                    if not dry_run:
                        MediaObject.objects.filter(pk=row.pk).update(size_bytes=item.size)
                continue

            # Untracked (or tracked as deleted but still stored). Leave recent
            # files alone: a save that stores a file then its record may be
            # between those two steps.
            if item.last_modified > cutoff:
                continue
            if is_media_referenced(item.key):
                counts["adopted"] += 1
                if not dry_run:
                    self._adopt(item)
            else:
                counts["deleted"] += 1
                if not dry_run:
                    storage.delete_object(item.key)
                    self._mark_deleted(item)

        stored = set(keys)
        missing = [
            key for key in MediaObject.objects.filter(
                file_key__startswith=prefix, status=MediaObject.Status.ATTACHED,
            ).values_list("file_key", flat=True)
            if key not in stored
        ]
        counts["missing"] = len(missing)
        if missing:
            # Records point at files that are gone; a person has to look at these.
            logger.warning("Branch %s: %d attached file(s) missing from storage, e.g. %s",
                           branch_id, len(missing), missing[:5])
        return counts

    def _location_fields(self, key):
        location = parse_media_key(key)
        if location is None:
            return {}
        class_id = location.class_id
        if class_id is not None and not Class.objects.filter(pk=class_id).exists():
            class_id = None
        return {"branch_id": location.branch_id, "class_obj_id": class_id, "category": location.category}

    def _adopt(self, item):
        now = timezone.now()
        MediaObject.objects.update_or_create(
            file_key=item.key,
            defaults={
                **self._location_fields(item.key),
                "size_bytes": item.size,
                "status": MediaObject.Status.ATTACHED,
                "attached_at": now,
                "deleted_at": None,
            },
        )

    def _mark_deleted(self, item):
        MediaObject.objects.update_or_create(
            file_key=item.key,
            defaults={
                **self._location_fields(item.key),
                "size_bytes": item.size,
                "status": MediaObject.Status.DELETED,
                "deleted_at": timezone.now(),
            },
        )
