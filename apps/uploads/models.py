from django.conf import settings
from django.db import models


class MediaObject(models.Model):
    """
    One stored file, with the branch it counts against.

    This table, not a bucket listing, is the source of storage usage:
    SUM(size_bytes) of pending + attached rows per branch. Rows are kept
    after deletion (status=deleted) so usage history and reconciliation
    can see what was removed.
    """

    class Status(models.TextChoices):
        # Presigned; the client may or may not have uploaded it yet. Counted
        # with the size it was signed for, so concurrent uploads are seen.
        PENDING = "pending", "Pending"
        ATTACHED = "attached", "Attached"
        DELETED = "deleted", "Deleted"

    file_key = models.CharField(max_length=512, unique=True)
    # SET_NULL: losing a branch/class must not drop the row that says the
    # file still exists in storage.
    branch = models.ForeignKey(
        "schools.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_objects",
    )
    class_obj = models.ForeignKey(
        "classes.Class",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_objects",
        db_column="class_id",
    )
    category = models.CharField(max_length=20, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    attached_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "media_objects"
        indexes = [
            models.Index(fields=["branch", "status"], name="media_obj_branch_status"),
            models.Index(fields=["status", "created_at"], name="media_obj_status_created"),
        ]

    def __str__(self):
        return self.file_key


class StorageAddOn(models.Model):
    """
    Retired: storage add-on requests approved by hand. Storage is now bought as
    a subscription add-on (apps.branch_subscriptions). Approved rows were
    carried into a storage_bytes override by branch_subscriptions 0002; the
    table is dropped in a later release.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    branch = models.ForeignKey("schools.Branch", on_delete=models.CASCADE, related_name="storage_addons")
    size_bytes = models.PositiveBigIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    note = models.TextField(blank=True)
    review_note = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "storage_addons"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["branch", "status"], name="storage_addon_branch_status")]

    def __str__(self):
        return f"{self.branch_id}: {self.size_bytes} bytes ({self.status})"
