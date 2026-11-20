"""
Branch storage usage, read from MediaObject.

Used bytes are pending + attached rows: a presigned upload counts from the
moment it is signed, until its upload URL has lapsed (an abandoned presign
stops counting then, even before cleanup_orphaned_uploads removes it).

Capacity comes from the branch subscription (feature storage_bytes: the plan
limit + storage add-ons, or a custom override). ensure_capacity rejects a new
upload that would go over it, and any upload while the subscription has
expired (read-only), unless settings.ENFORCE_BRANCH_STORAGE_CAPACITY is off.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import BigIntegerField, Count, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.uploads.models import MediaObject
from plan_subscriptions import entitlements
from plan_subscriptions.exceptions import FeatureLocked, LimitReached

COUNTED_STATUSES = (MediaObject.Status.PENDING, MediaObject.Status.ATTACHED)
WARNING_PERCENT = 80
STORAGE_FEATURE = "storage_bytes"
# A pending upload stops counting this long after its URL lapsed.
PENDING_GRACE = timedelta(minutes=10)

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_OVER = "over"


def pending_cutoff():
    return timezone.now() - timedelta(seconds=settings.UPLOAD_METADATA_TTL) - PENDING_GRACE


def counted_media():
    return MediaObject.objects.filter(
        Q(status=MediaObject.Status.ATTACHED)
        | Q(status=MediaObject.Status.PENDING, created_at__gte=pending_cutoff())
    )


def with_storage_used(branches):
    """Annotate storage_used_bytes on a Branch queryset (a subquery, so joins elsewhere can't double it)."""
    used = (
        counted_media()
        .filter(branch=OuterRef("pk"))
        .order_by()
        .values("branch")
        .annotate(total=Sum("size_bytes"))
        .values("total")
    )
    return branches.annotate(
        storage_used_bytes=Coalesce(Subquery(used, output_field=BigIntegerField()), Value(0)),
    )


def used_bytes(branch_id) -> int:
    return counted_media().filter(branch_id=branch_id).aggregate(total=Sum("size_bytes"))["total"] or 0


def capacity_of(branch):
    """The branch's storage limit from its subscription; None = unlimited, 0 = none."""
    return entitlements.raw_limit(branch, STORAGE_FEATURE)


def storage_state(branch) -> str:
    """"active", "read_only" (subscription expired: no new uploads) or "off"."""
    return entitlements.state(branch, STORAGE_FEATURE)


def addon_bytes_of(branch) -> int:
    """Storage bought as add-ons (active purchases), for display."""
    from plan_subscriptions.models import AddOnFeature, SubscriptionAddOn

    total = 0
    purchases = SubscriptionAddOn.objects.filter(
        subscription__subscriber_id=branch.pk,
        status__in=(SubscriptionAddOn.Status.ACTIVE, SubscriptionAddOn.Status.ENDING),
    ).select_related("addon")
    for purchase in purchases:
        for row in AddOnFeature.objects.filter(addon=purchase.addon, feature__code=STORAGE_FEATURE):
            if row.mode == AddOnFeature.Mode.INCREMENT and row.value:
                total += row.value * purchase.quantity
    return total


def has_storage_override(branch) -> bool:
    from plan_subscriptions.models import FeatureOverride

    return FeatureOverride.objects.filter(subscriber_id=branch.pk, feature__code=STORAGE_FEATURE).exists()


def usage_status(used: int, capacity) -> str:
    if capacity is None:
        return STATUS_OK
    if used > capacity:
        return STATUS_OVER
    if capacity and used * 100 >= capacity * WARNING_PERCENT:
        return STATUS_WARNING
    return STATUS_OK


def usage_summary(branch, used: int) -> dict:
    capacity = capacity_of(branch)
    addons = addon_bytes_of(branch)
    return {
        "branch_id": branch.pk,
        "branch_name": branch.name,
        "school_id": branch.school_id,
        "used_bytes": used,
        "capacity_bytes": capacity,
        "base_capacity_bytes": None if capacity is None else max(0, capacity - addons),
        "addon_bytes": addons,
        # True while the plan (and add-ons) decide; False with a custom per-branch limit.
        "capacity_is_default": not has_storage_override(branch),
        "storage_state": storage_state(branch),
        "percent": round(used * 100 / capacity, 2) if capacity else None,
        "status": usage_status(used, capacity),
    }


def _category_rows(rows):
    return sorted(
        ({"category": row["category"] or "other", "used_bytes": row["used"], "files": row["files"]} for row in rows),
        key=lambda row: -row["used_bytes"],
    )


def branch_storage_report(branch) -> dict:
    """Usage summary plus a breakdown per category and per class."""
    rows = list(
        counted_media()
        .filter(branch=branch)
        .order_by()
        .values("class_obj_id", "class_obj__name", "category")
        .annotate(used=Sum("size_bytes"), files=Count("pk"))
    )
    pending = counted_media().filter(branch=branch, status=MediaObject.Status.PENDING).aggregate(
        total=Sum("size_bytes"),
    )["total"] or 0

    by_category = {}
    classes = {}
    for row in rows:
        category = by_category.setdefault(row["category"], {"category": row["category"], "used": 0, "files": 0})
        category["used"] += row["used"]
        category["files"] += row["files"]
        if row["class_obj_id"] is not None:
            classes.setdefault(row["class_obj_id"], {"name": row["class_obj__name"], "rows": []})["rows"].append(row)

    by_class = [
        {
            "class_id": class_id,
            "class_name": entry["name"],
            "used_bytes": sum(row["used"] for row in entry["rows"]),
            "files": sum(row["files"] for row in entry["rows"]),
            "by_category": _category_rows(entry["rows"]),
        }
        for class_id, entry in classes.items()
    ]
    by_class.sort(key=lambda row: -row["used_bytes"])

    used = sum(row["used"] for row in rows)
    return {
        **usage_summary(branch, used),
        "pending_bytes": pending,
        "files": sum(row["files"] for row in rows),
        "by_category": _category_rows(by_category.values()),
        "by_class": by_class,
    }


def branches_by_usage(branches) -> list:
    """Summaries for every branch, fullest (by percent of capacity) first."""
    summaries = [usage_summary(branch, branch.storage_used_bytes) for branch in with_storage_used(branches)]
    summaries.sort(key=lambda row: (-(row["percent"] or 0), -row["used_bytes"], row["branch_id"]))
    return summaries


def ensure_capacity(branch_id: int, incoming_bytes: int) -> None:
    """
    Raise StorageFullError if incoming_bytes would take the branch past its
    capacity, or StorageLockedError while its subscription has expired.

    Call it inside transaction.atomic() and record the upload in the same
    transaction: the branch row stays locked until commit, so two uploads
    racing for the last free bytes are checked one after the other.
    """
    if not settings.ENFORCE_BRANCH_STORAGE_CAPACITY:
        return
    from apps.schools.models import Branch
    from apps.uploads.services.media import StorageFullError, StorageLockedError

    branch = Branch.objects.select_for_update().only("pk").get(pk=branch_id)
    used = used_bytes(branch_id)
    try:
        entitlements.check_limit(branch, STORAGE_FEATURE, used=used, adding=incoming_bytes)
    except FeatureLocked as error:
        raise StorageLockedError(branch_id, error.state)
    except LimitReached as error:
        raise StorageFullError(branch_id, used, error.limit, incoming_bytes)
