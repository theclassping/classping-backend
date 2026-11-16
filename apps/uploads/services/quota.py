"""
What a branch can do when its storage is full: reset (clear) stored images
by category and class, or request an add-on that a superadmin approves.
"""
import logging
from typing import Optional

from django.apps import apps
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.uploads.models import MediaObject, StorageAddOn

logger = logging.getLogger(__name__)

GIB = 1024 ** 3
MAX_ADDON_GB = 1000

# Payment proofs are financial records and are never reset.
RESETTABLE_CATEGORIES = ("activities", "assessments", "students", "guardians", "general")
RESET_MODELS = (
    "schools.School", "students.Student", "guardians.Guardian",
    "activities.ActivityImage", "assessments.AssessmentImage",
)
# Keys per UPDATE and per deletion task.
RESET_CHUNK = 500


class StorageActionError(ValueError):
    """A reset or add-on request the caller can fix (shown as a 400)."""


# --- Reset -----------------------------------------------------------------

def reset_candidates(branch, category: str, class_id: Optional[int] = None):
    """Attached files of one category (optionally one class) in the branch."""
    if category not in RESETTABLE_CATEGORIES:
        raise StorageActionError(
            f"category must be one of: {', '.join(RESETTABLE_CATEGORIES)}. Payment proofs cannot be reset."
        )
    if class_id is not None and not branch.classes.filter(pk=class_id).exists():
        raise StorageActionError("class_id is not a class of this branch.")
    rows = MediaObject.objects.filter(branch=branch, category=category, status=MediaObject.Status.ATTACHED)
    if class_id is not None:
        rows = rows.filter(class_obj_id=class_id)
    return rows


def summarize(rows) -> dict:
    totals = rows.aggregate(files=Count("pk"), bytes=Sum("size_bytes"))
    return {"files": totals["files"], "bytes": totals["bytes"] or 0}


def reset_branch_media(branch, category: str, class_id: Optional[int], user) -> dict:
    """
    Clear image_data on every record that shows one of these files, then
    delete the files in the background. Records themselves are kept.

    Space is freed as each file is deleted from storage. A file whose delete
    fails stays counted (and attached in MediaObject), so running the same
    reset again retries it.
    """
    rows = reset_candidates(branch, category, class_id)
    summary = summarize(rows)
    keys = list(rows.values_list("file_key", flat=True))
    if not keys:
        return summary

    with transaction.atomic():
        for start in range(0, len(keys), RESET_CHUNK):
            chunk = keys[start:start + RESET_CHUNK]
            match = Q(image_data__id__in=chunk) | Q(image_data__object_key__in=chunk)
            for label in RESET_MODELS:
                # update() skips the media signals on purpose: the files are
                # deleted below, in bulk, after the records stop naming them.
                apps.get_model(label)._base_manager.filter(match).update(image_data=None)

        from apps.uploads.tasks import delete_reset_media_task

        def enqueue():
            for start in range(0, len(keys), RESET_CHUNK):
                delete_reset_media_task.delay(keys[start:start + RESET_CHUNK])

        transaction.on_commit(enqueue)

    logger.info(
        "Storage reset: branch=%s category=%s class=%s files=%s bytes=%s by user=%s",
        branch.pk, category, class_id, summary["files"], summary["bytes"], getattr(user, "pk", None),
    )
    return summary


def delete_reset_files(keys) -> int:
    """Delete files no record names any more; returns how many were deleted."""
    from apps.uploads.references import is_media_referenced
    from apps.uploads.services.media import MediaService
    from apps.uploads.tracking import record_deleted

    deleted = 0
    for key in keys:
        try:
            if is_media_referenced(key):
                continue
            MediaService.delete_object(key)
            record_deleted(key)
            deleted += 1
        except Exception:
            logger.exception("Unable to delete reset media %s", key)
    return deleted


# --- Add-ons ---------------------------------------------------------------

def request_addon(branch, size_gb: int, note: str, user) -> StorageAddOn:
    if not isinstance(size_gb, int) or isinstance(size_gb, bool) or not 1 <= size_gb <= MAX_ADDON_GB:
        raise StorageActionError(f"size_gb must be a whole number from 1 to {MAX_ADDON_GB}.")
    with transaction.atomic():
        # Locked so two requests at once cannot both pass the pending check.
        type(branch).objects.select_for_update().only("pk").get(pk=branch.pk)
        if branch.storage_addons.filter(status=StorageAddOn.Status.PENDING).exists():
            raise StorageActionError("This branch already has a pending add-on request.")
        return StorageAddOn.objects.create(
            branch=branch, size_bytes=size_gb * GIB, note=note or "", requested_by=user,
        )


def cancel_addon(addon: StorageAddOn) -> StorageAddOn:
    with transaction.atomic():
        addon = StorageAddOn.objects.select_for_update().get(pk=addon.pk)
        if addon.status != StorageAddOn.Status.PENDING:
            raise StorageActionError("Only a pending request can be cancelled.")
        addon.status = StorageAddOn.Status.CANCELLED
        addon.reviewed_at = timezone.now()
        addon.save(update_fields=["status", "reviewed_at"])
    return addon


def review_addon(addon: StorageAddOn, approve: bool, user, note: str = "") -> StorageAddOn:
    """Superadmin decision. Approval raises the branch's capacity immediately."""
    from apps.schools.models import Branch

    with transaction.atomic():
        # Branch first, in the same order as ensure_capacity, so an approval
        # and an upload check never deadlock.
        Branch.objects.select_for_update().only("pk").get(pk=addon.branch_id)
        addon = StorageAddOn.objects.select_for_update().get(pk=addon.pk)
        if addon.status != StorageAddOn.Status.PENDING:
            raise StorageActionError("This request has already been handled.")
        addon.status = StorageAddOn.Status.APPROVED if approve else StorageAddOn.Status.REJECTED
        addon.reviewed_by = user
        addon.reviewed_at = timezone.now()
        addon.review_note = note or ""
        addon.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    logger.info("Storage add-on %s %s by user=%s", addon.pk, addon.status, getattr(user, "pk", None))
    return addon
