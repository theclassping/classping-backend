from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.uploads.services.media import MediaService
from apps.uploads.storage import get_storage


class Command(BaseCommand):
    help = "Delete expired, incomplete upload objects from storage."

    def handle(self, *args, **options):
        client = MediaService._redis()
        if not client:
            self.stdout.write("Redis is not configured; no orphan cleanup performed.")
            return

        keys = client.zrangebyscore(
            MediaService._pending_uploads_key(), 0, timezone.now().timestamp()
        )
        storage = get_storage()
        deleted = 0
        for file_key in keys:
            try:
                storage.delete_object(file_key)
                deleted += 1
            finally:
                client.delete(MediaService._upload_cache_key(file_key))
                client.zrem(MediaService._pending_uploads_key(), file_key)

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} orphaned upload(s)."))
