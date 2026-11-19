"""
Branch:  a new branch starts its trial on Starter (PLAN_SUBSCRIPTIONS["TRIAL_PLAN"]).
         The legacy admin-web field storage_capacity_bytes is kept in step with
         a storage_bytes override until it is removed.
Student: every save that adds an active student to a branch (create,
         re-activate, move branch) is checked against max_students. One check
         here covers the API, admin web forms, CSV import and seeds.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.schools.models import Branch
from apps.students.models import Student
from plan_subscriptions import entitlements, services
from plan_subscriptions.models import Feature, FeatureOverride, Plan

from apps.classes.models import Class, ClassStudent

from .usage import branches_of, ensure_student_capacity, is_active, new_branches_for_student

logger = logging.getLogger(__name__)

LEGACY_STORAGE_REASON = "Custom capacity set on the branch"


@receiver(post_save, sender=Branch, dispatch_uid="branch_subscriptions_branch_saved")
def branch_saved(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        try:
            # In the same transaction as the branch: it is never without a subscription.
            services.start_trial(instance)
        except Plan.DoesNotExist:
            # Catalog missing (fresh database, flushed tests): load it and retry.
            from plan_subscriptions.catalog import load_catalog

            from .catalog import CATALOG

            load_catalog(CATALOG)
            services.start_trial(instance)
    _sync_legacy_storage(instance)


def _sync_legacy_storage(branch):
    feature = Feature.objects.filter(code="storage_bytes").first()
    if feature is None:
        return
    override = FeatureOverride.objects.filter(subscriber_id=branch.pk, feature=feature).first()
    if branch.storage_capacity_bytes is not None:
        if override is None or override.value != branch.storage_capacity_bytes:
            FeatureOverride.objects.update_or_create(
                subscriber_id=branch.pk, feature=feature,
                defaults={"value": branch.storage_capacity_bytes, "reason": LEGACY_STORAGE_REASON},
            )
            entitlements.invalidate(branch.pk)
    elif override is not None and override.reason == LEGACY_STORAGE_REASON:
        override.delete()
        entitlements.invalidate(branch.pk)


@receiver(pre_save, sender=Student, dispatch_uid="branch_subscriptions_student_limit")
def student_limit(sender, instance, raw=False, **kwargs):
    """Create, re-activate or move a student: each branch it newly counts in must have a seat."""
    if raw:
        return
    before = Student.objects.filter(pk=instance.pk).only("branch_id", "status").first() if instance.pk else None
    branches = new_branches_for_student(before, instance.branch_id, instance.status)
    if branches:
        with transaction.atomic():
            for branch_id in sorted(branches):
                ensure_student_capacity(branch_id, 1, exclude_ids=[instance.pk] if instance.pk else ())


@receiver(pre_save, sender=ClassStudent, dispatch_uid="branch_subscriptions_enrollment_limit")
def enrollment_limit(sender, instance, raw=False, **kwargs):
    """Putting an active student in a current class of a branch it isn't in yet takes a seat there."""
    if raw or not instance.is_current:
        return
    student = Student.objects.filter(pk=instance.student_id).only("status", "branch_id").first()
    if student is None or not is_active(student.status):
        return
    branch_id = Class.objects.filter(pk=instance.class_obj_id).values_list("branch_id", flat=True).first()
    if not branch_id or branch_id in branches_of(student.pk, exclude_assignment_id=instance.pk):
        return
    with transaction.atomic():
        ensure_student_capacity(branch_id, 1, exclude_ids=[student.pk])
