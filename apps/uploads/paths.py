"""
Branch-rooted object keys for uploaded media.

Every new upload lives under the branch it belongs to, so storage can be
audited and cleaned up per branch with a prefix listing:

    branch_{branch_id}/class_{class_id}/{category}/{uuid}{ext}   activities, assessments, payments
    branch_{branch_id}/{category}/{uuid}{ext}                    students, guardians, general

The server always builds the key; clients only name the purpose and the
record it is for (see resolve_upload_location). Keys written before this
layout ("{yyyy}/{mm}/{dd}/{uuid}{ext}") stay valid and parse to None.
"""
import re
import uuid
from dataclasses import dataclass
from typing import Optional, Set

from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import ValidationError

# purpose sent by the client -> folder name in the key
PURPOSE_CATEGORIES = {
    "activity": "activities",
    "assessment": "assessments",
    "payment": "payments",
    "student": "students",
    "guardian": "guardians",
    "general": "general",
}
# Purposes stored under a class folder; the rest sit directly under the branch.
CLASS_PURPOSES = frozenset({"activity", "assessment", "payment"})
CLASS_CATEGORIES = frozenset(PURPOSE_CATEGORIES[p] for p in CLASS_PURPOSES)

_KEY_PATTERN = re.compile(
    r"^branch_(?P<branch>\d+)/(?:class_(?P<class>\d+)/)?(?P<category>[a-z]+)/[^/]+$"
)


class UploadTargetNotFound(Exception):
    """The class or branch named for an upload is not visible to the user."""


class MediaLocationMismatch(ValidationError):
    """A branch-rooted key was attached to a record in another branch, class or category."""

    def __init__(self):
        super().__init__({"image_data": "This image was uploaded for a different record. Upload it again for this one."})


@dataclass(frozen=True)
class MediaLocation:
    branch_id: int
    class_id: Optional[int]
    category: str


def build_media_key(purpose: str, branch_id: int, class_id: Optional[int] = None, extension: str = "") -> str:
    """Return a new, unique object key for an upload of this purpose."""
    if purpose not in PURPOSE_CATEGORIES:
        raise ValueError(f"Unknown upload purpose: {purpose}")
    if not branch_id:
        raise ValueError("branch_id is required")
    if purpose in CLASS_PURPOSES and not class_id:
        raise ValueError(f"class_id is required for {purpose} uploads")

    parts = [f"branch_{int(branch_id)}"]
    if purpose in CLASS_PURPOSES:
        parts.append(f"class_{int(class_id)}")
    parts.append(PURPOSE_CATEGORIES[purpose])
    parts.append(f"{uuid.uuid4().hex}{extension}")
    return "/".join(parts)


def build_key_for_location(location: MediaLocation, extension: str = "") -> str:
    purpose = next(p for p, c in PURPOSE_CATEGORIES.items() if c == location.category)
    return build_media_key(purpose, location.branch_id, location.class_id, extension)


def parse_media_key(key: str) -> Optional[MediaLocation]:
    """Return where a branch-rooted key belongs, or None for legacy/other keys."""
    match = _KEY_PATTERN.match(key or "")
    if not match:
        return None
    category = match["category"]
    class_id = int(match["class"]) if match["class"] else None
    # A class folder only ever holds class categories, and vice versa.
    if category not in PURPOSE_CATEGORIES.values() or (class_id is None) == (category in CLASS_CATEGORIES):
        return None
    return MediaLocation(branch_id=int(match["branch"]), class_id=class_id, category=category)


# ----------------------------------------------------------------------
# Presign: which branch/class does a new upload go to?
# ----------------------------------------------------------------------

def resolve_upload_location(user, purpose: str, class_id=None, branch_id=None) -> MediaLocation:
    """
    Decide the branch (and class) for an upload, using only records the
    user can see.

    Class purposes take the branch from the class. Branch purposes use, in
    order: the branch_id sent, the uploader's staff branch, or the only
    branch the user can see; otherwise branch_id is required.

    Raises UploadTargetNotFound when the class/branch is not visible, and
    MediaInputError when required context is missing.
    """
    from apps.classes.models import Class
    from apps.core.access import scope_queryset
    from apps.schools.models import Branch
    from apps.uploads.services.media import MediaInputError

    category = PURPOSE_CATEGORIES[purpose]

    if purpose in CLASS_PURPOSES:
        if not class_id:
            raise MediaInputError(f"class_id is required for {purpose} uploads.")
        class_obj = scope_queryset(Class.objects.all(), user).filter(pk=class_id).first()
        if class_obj is None:
            raise UploadTargetNotFound("Class not found.")
        return MediaLocation(branch_id=class_obj.branch_id, class_id=class_obj.pk, category=category)

    visible_branches = scope_queryset(Branch.objects.all(), user)
    if branch_id:
        if not visible_branches.filter(pk=branch_id).exists():
            raise UploadTargetNotFound("Branch not found.")
        return MediaLocation(branch_id=int(branch_id), class_id=None, category=category)

    staff = getattr(user, "staff", None)
    if staff is not None and staff.branch_id:
        return MediaLocation(branch_id=staff.branch_id, class_id=None, category=category)

    only = list(visible_branches.values_list("pk", flat=True)[:2])
    if len(only) == 1:
        return MediaLocation(branch_id=only[0], class_id=None, category=category)
    raise MediaInputError(f"branch_id is required for {purpose} uploads.")


# ----------------------------------------------------------------------
# Attach: does a key belong to the record it is being saved on?
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class ExpectedLocation:
    category: str
    class_id: Optional[int] = None
    # None means "any branch": the record can't name its branch yet
    # (e.g. a guardian saved before being linked to a student).
    branch_ids: Optional[Set[int]] = None


def _class_location(category, class_obj):
    return ExpectedLocation(category=category, class_id=class_obj.pk, branch_ids={class_obj.branch_id})


def _student_branch_ids(students_qs):
    ids = set(students_qs.exclude(branch_id=None).values_list("branch_id", flat=True))
    ids |= set(students_qs.values_list("class_students__class_obj__branch_id", flat=True))
    ids.discard(None)
    return ids


def expected_location(instance) -> Optional[ExpectedLocation]:
    """Return where media for this record must live, or None for models without a rule."""
    label = instance._meta.label

    if label == "activities.ActivityImage":
        return _class_location("activities", instance.activity.class_obj)
    if label == "assessments.AssessmentImage":
        return _class_location("assessments", instance.student_assessment.assessment.class_obj)
    if label == "payments.PaymentProof":
        return _class_location("payments", instance.payment.student_invoice.class_student.class_obj)

    if label == "students.Student":
        if instance.branch_id:
            return ExpectedLocation(category="students", branch_ids={instance.branch_id})
        if instance.pk:
            from apps.students.models import Student
            ids = _student_branch_ids(Student.objects.filter(pk=instance.pk))
            return ExpectedLocation(category="students", branch_ids=ids or None)
        return ExpectedLocation(category="students")

    if label == "guardians.Guardian":
        if instance.pk:
            from apps.students.models import Student
            ids = _student_branch_ids(Student.objects.filter(student_guardians__guardian_id=instance.pk))
            return ExpectedLocation(category="guardians", branch_ids=ids or None)
        return ExpectedLocation(category="guardians")

    if label == "schools.School":
        ids = set(instance.branches.values_list("pk", flat=True)) if instance.pk else set()
        return ExpectedLocation(category="general", branch_ids=ids or None)

    return None


def check_media_location(instance, key: str) -> None:
    """Raise MediaLocationMismatch when a branch-rooted key doesn't fit instance."""
    location = parse_media_key(key)
    if location is None:
        # Legacy date-based keys predate branch folders.
        return
    expected = expected_location(instance)
    if expected is None:
        return
    if location.category != expected.category:
        raise MediaLocationMismatch()
    if expected.class_id is not None and location.class_id != expected.class_id:
        raise MediaLocationMismatch()
    if expected.branch_ids is not None and location.branch_id not in expected.branch_ids:
        raise MediaLocationMismatch()


def instance_media_location(instance) -> Optional[MediaLocation]:
    """
    Where a server-side upload (admin web) onto instance belongs, or None
    while the record can't name its branch (a school without branches, a
    guardian without children, a student without a branch or class).
    """
    try:
        expected = expected_location(instance)
    except ObjectDoesNotExist:
        # Parent record not linked yet.
        return None
    if expected is None or not expected.branch_ids:
        return None
    return MediaLocation(min(expected.branch_ids), expected.class_id, expected.category)


def media_key_for_instance(instance, extension: str = "") -> Optional[str]:
    """Build a key for a server-side upload onto instance, or None if it has no branch yet."""
    location = instance_media_location(instance)
    return build_key_for_location(location, extension) if location else None
