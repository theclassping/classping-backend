from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.uploads.models import MediaObject
from apps.uploads.services.media import MediaService
from apps.uploads.storage import get_storage
from apps.uploads.references import is_media_referenced
from apps.uploads.tracking import record_deleted

# Presigned URLs live at most UPLOAD_METADATA_TTL; wait a little longer so
# an upload finishing right at expiry can still be attached.
PENDING_GRACE = timedelta(minutes=10)


class Command(BaseCommand):
    help = "Delete expired, incomplete upload objects from storage."

    def handle(self, *args, **options):
        deleted = self._cleanup_redis_pending()
        deleted += self._cleanup_tracked_pending()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} orphaned upload(s)."))

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
        cutoff = timezone.now() - timedelta(seconds=settings.UPLOAD_METADATA_TTL) - PENDING_GRACE
        keys = list(
            MediaObject.objects.filter(status=MediaObject.Status.PENDING, created_at__lt=cutoff)
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
