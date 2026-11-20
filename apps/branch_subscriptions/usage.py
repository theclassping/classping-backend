"""
How much of each limit a branch uses, and the checks that enforce them.

Students: a student belongs to a branch through Student.branch or a current
class in that branch (the same rule as apps.core.access). Only active
students count; the status is compared without case (the model default is
"ACTIVE" but the choice is "active").
Storage: pending + attached media (apps.uploads.usage).
"""
from collections import Counter

from django.db.models import Q

from plan_subscriptions import entitlements
from plan_subscriptions.exceptions import FeatureLocked, LimitReached

from apps.schools.models import Branch

from .errors import StudentLimitReached, SubscriptionFeatureLocked

# Admin web catches these around student saves.
SUBSCRIPTION_LIMIT_ERRORS = (StudentLimitReached, SubscriptionFeatureLocked)

ACTIVE_STUDENT = "active"


def is_active(status):
    return str(status or "").lower() == ACTIVE_STUDENT


def _in_branch(branch_id):
    return Q(branch_id=branch_id) | Q(class_students__is_current=True, class_students__class_obj__branch_id=branch_id)


def active_students(branch_id, exclude_ids=()):
    from apps.students.models import Student

    qs = Student.objects.filter(status__iexact=ACTIVE_STUDENT).filter(_in_branch(branch_id))
    if exclude_ids:
        qs = qs.exclude(pk__in=list(exclude_ids))
    return qs.distinct().count()


def branches_of(student_id, exclude_assignment_id=None):
    """Branches a saved student counts in now: its own branch and current classes."""
    from apps.classes.models import ClassStudent
    from apps.students.models import Student

    ids = set(Student.objects.filter(pk=student_id).exclude(branch_id=None).values_list("branch_id", flat=True))
    assignments = ClassStudent.objects.filter(student_id=student_id, is_current=True)
    if exclude_assignment_id:
        assignments = assignments.exclude(pk=exclude_assignment_id)
    ids |= set(assignments.values_list("class_obj__branch_id", flat=True))
    ids.discard(None)
    return ids


def usage_of(branch):
    from apps.uploads.usage import used_bytes

    return {"max_students": active_students(branch.pk), "storage_bytes": used_bytes(branch.pk)}


def ensure_student_capacity(branch_id, adding=1, exclude_ids=()):
    """
    Raise StudentLimitReached / SubscriptionFeatureLocked (API errors) unless
    ``adding`` more active students fit in the branch. Call inside
    transaction.atomic(): the branch row is locked so two requests can't
    both take the last seat.
    """
    if not branch_id or adding <= 0:
        return
    branch = Branch.objects.select_for_update().only("pk").get(pk=branch_id)
    used = active_students(branch_id, exclude_ids)
    try:
        entitlements.check_limit(branch, "max_students", used=used, adding=adding)
    except FeatureLocked as error:
        raise SubscriptionFeatureLocked(feature="max_students", state=error.state)
    except LimitReached as error:
        raise StudentLimitReached(
            limit=error.limit, used=error.used, adding=error.adding,
            plans=plans_that_fit(used + adding),
        )


def ensure_import_fits(rows):
    """Bulk import: every branch in the file must fit all its new active students at once."""
    per_branch = Counter(
        row.get("branch_id") for row in rows
        if row.get("branch_id") and is_active(row.get("status") or ACTIVE_STUDENT)
    )
    for branch_id, count in per_branch.items():
        ensure_student_capacity(int(branch_id), count)


def plans_that_fit(students):
    from plan_subscriptions.models import Plan

    rows = []
    for plan in Plan.objects.filter(is_active=True, is_public=True).prefetch_related("plan_features__feature"):
        values = {pf.feature.code: pf.value for pf in plan.plan_features.all()}
        limit = values.get("max_students", 0)
        if limit is None or limit >= students:
            price = plan.current_price()
            rows.append({"code": plan.code, "name": plan.name, "max_students": limit,
                         "amount": str(price.amount) if price else None})
    return rows


def new_branches_for_student(before, branch_id, status):
    """
    Branches a student save adds an active student to. ``before`` is the
    saved row (None on create). Current classes don't change on this save, so
    a student already counted in a branch is not counted again.
    """
    if not is_active(status):
        return set()
    if before is None:
        return {branch_id} if branch_id else set()
    current = branches_of(before.pk)
    target = set(current)
    if before.branch_id and before.branch_id != branch_id:
        # Moving away from the old branch (unless still in a class there).
        from apps.classes.models import ClassStudent

        if not ClassStudent.objects.filter(student_id=before.pk, is_current=True,
                                           class_obj__branch_id=before.branch_id).exists():
            target.discard(before.branch_id)
    if branch_id:
        target.add(branch_id)
    if not is_active(before.status):
        return target
    return target - current
