"""
Keep MediaObject in step with storage: one row per stored file, with the
branch it counts against. Callers are the presign service, the media
signals (attach/replace/delete) and the cleanup command.
"""
import logging
from typing import Any, Dict, Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from apps.uploads.models import MediaObject
from apps.uploads.paths import MediaLocation, expected_location, parse_media_key

logger = logging.getLogger(__name__)


def record_presigned(file_key: str, location: MediaLocation, size: int, content_type: str, user_id) -> None:
    """A presigned upload counts against its branch from the moment it is signed."""
    MediaObject.objects.create(
        file_key=file_key,
        branch_id=location.branch_id,
        class_obj_id=location.class_id,
        category=location.category,
        size_bytes=size,
        content_type=content_type,
        status=MediaObject.Status.PENDING,
        created_by_id=user_id,
    )


def location_for(instance, key: str) -> Optional[MediaLocation]:
    """Branch-rooted keys name their location; legacy keys take it from the record."""
    location = parse_media_key(key)
    if location is not None:
        return location
    try:
        expected = expected_location(instance)
    except ObjectDoesNotExist:
        return None
    if expected is None:
        return None
    branch_id = min(expected.branch_ids) if expected.branch_ids else None
    if branch_id is None:
        return None
    return MediaLocation(branch_id, expected.class_id, expected.category)


def metadata_value(image_data: Dict[str, Any], name: str):
    # Older rows nest file details under "metadata" (see MediaService.complete_upload).
    return image_data.get(name) or (image_data.get("metadata") or {}).get(name)


def record_attached(instance, key: str, image_data: Dict[str, Any]) -> None:
    """Mark key as stored on instance, with the size storage reported for it."""
    image_data = image_data if isinstance(image_data, dict) else {}
    location = location_for(instance, key)
    defaults = {
        "status": MediaObject.Status.ATTACHED,
        "attached_at": timezone.now(),
        "deleted_at": None,
    }
    if location is not None:
        defaults.update(
            branch_id=location.branch_id,
            class_obj_id=location.class_id,
            category=location.category,
        )
    size = metadata_value(image_data, "size")
    if size:
        defaults["size_bytes"] = int(size)
    content_type = metadata_value(image_data, "content_type") or metadata_value(image_data, "mime_type")
    if content_type:
        defaults["content_type"] = content_type
    MediaObject.objects.update_or_create(file_key=key, defaults=defaults)


def record_deleted(key: str) -> None:
    """The object is gone from storage; stop counting it."""
    MediaObject.objects.filter(file_key=key).exclude(status=MediaObject.Status.DELETED).update(
        status=MediaObject.Status.DELETED,
        deleted_at=timezone.now(),
    )
