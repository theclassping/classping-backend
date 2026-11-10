"""
Branch storage usage, read from MediaObject.

Used bytes are pending + attached rows: a presigned upload counts from the
moment it is signed. Capacity is monitored only; nothing here blocks uploads.
"""
from django.conf import settings
from django.db.models import BigIntegerField, Count, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.uploads.models import MediaObject

COUNTED_STATUSES = (MediaObject.Status.PENDING, MediaObject.Status.ATTACHED)
WARNING_PERCENT = 80

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_OVER = "over"


def counted_media():
    return MediaObject.objects.filter(status__in=COUNTED_STATUSES)


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


def capacity_of(branch) -> int:
    if branch.storage_capacity_bytes is not None:
        return branch.storage_capacity_bytes
    return settings.DEFAULT_BRANCH_STORAGE_BYTES


def usage_status(used: int, capacity: int) -> str:
    if used > capacity:
        return STATUS_OVER
    if capacity and used * 100 >= capacity * WARNING_PERCENT:
        return STATUS_WARNING
    return STATUS_OK


def usage_summary(branch, used: int) -> dict:
    capacity = capacity_of(branch)
    return {
        "branch_id": branch.pk,
        "branch_name": branch.name,
        "school_id": branch.school_id,
        "used_bytes": used,
        "capacity_bytes": capacity,
        "capacity_is_default": branch.storage_capacity_bytes is None,
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
