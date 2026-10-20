"""Role-aware queryset and related-field scoping for the API."""
from django.db.models import Q


def scope_queryset(queryset, user):
    """Limit school records to the authenticated user's own school context."""
    if not user or not user.is_authenticated or user.is_superuser:
        return queryset

    role = str(user.role).upper()
    if role == "ADMIN":
        return queryset

    model = queryset.model
    name = model._meta.model_name

    # Geographic locations are shared reference data, not school records.
    if name == "location":
        return queryset

    # A parent can see only their own guardian profile and linked children.
    if role == "PARENT":
        own_guardian = Q(user_id=user.pk) if name == "guardian" else Q(pk__in=[])
        scopes = {
            "student": Q(student_guardians__guardian__user_id=user.pk),
            "studentguardian": Q(guardian__user_id=user.pk),
            "studentinvoice": Q(class_student__student__student_guardians__guardian__user_id=user.pk),
            "payment": Q(student_invoice__class_student__student__student_guardians__guardian__user_id=user.pk),
            "paymentproof": Q(payment__student_invoice__class_student__student__student_guardians__guardian__user_id=user.pk),
            "class": Q(class_students__student__student_guardians__guardian__user_id=user.pk),
            "classstudent": Q(student__student_guardians__guardian__user_id=user.pk),
            "classteacher": Q(class_obj__class_students__student__student_guardians__guardian__user_id=user.pk),
            "branch": (
                Q(students__student_guardians__guardian__user_id=user.pk)
                | Q(classes__class_students__student__student_guardians__guardian__user_id=user.pk)
            ),
            "school": (
                Q(branches__students__student_guardians__guardian__user_id=user.pk)
                | Q(branches__classes__class_students__student__student_guardians__guardian__user_id=user.pk)
            ),
            "activity": Q(is_publish=True, activity_students__student__student_guardians__guardian__user_id=user.pk),
            "activityimage": Q(activity__is_publish=True, student__student_guardians__guardian__user_id=user.pk),
            "activitystudent": Q(activity__is_publish=True, student__student_guardians__guardian__user_id=user.pk),
            "assessment": Q(status="published", student_assessments__student__student_guardians__guardian__user_id=user.pk),
            "studentassessment": Q(assessment__status="published", student__student_guardians__guardian__user_id=user.pk),
            "assessmentimage": Q(student_assessment__assessment__status="published", student_assessment__student__student_guardians__guardian__user_id=user.pk),
            "user": Q(pk=user.pk),
        }
        if name == "guardian":
            return queryset.filter(own_guardian)
        if name in scopes:
            return queryset.filter(scopes[name]).distinct()
        return queryset.none()

    staff_profile = getattr(user, "staff", None)
    if staff_profile is None:
        return queryset.none()

    branch_id = staff_profile.branch_id
    if role == "TEACHER" or staff_profile.staff_type == "teacher":
        assigned_class = Q(class_teachers__staff__user_id=user.pk)
        scopes = {
            "staff": Q(user_id=user.pk),
            "class": assigned_class,
            "classteacher": Q(staff__user_id=user.pk),
            "classstudent": Q(class_obj__class_teachers__staff__user_id=user.pk),
            "student": Q(class_students__class_obj__class_teachers__staff__user_id=user.pk),
            "studentguardian": Q(student__class_students__class_obj__class_teachers__staff__user_id=user.pk),
            "guardian": Q(student_guardians__student__class_students__class_obj__class_teachers__staff__user_id=user.pk),
            "academicyear": Q(branch__classes__class_teachers__staff__user_id=user.pk),
            "branch": Q(pk=branch_id),
            "school": Q(branches__id=branch_id),
            "studentinvoice": Q(class_student__class_obj__class_teachers__staff__user_id=user.pk),
            "payment": Q(student_invoice__class_student__class_obj__class_teachers__staff__user_id=user.pk),
            "paymentproof": Q(payment__student_invoice__class_student__class_obj__class_teachers__staff__user_id=user.pk),
            "activity": Q(class_teacher__staff__user_id=user.pk),
            "activityimage": Q(activity__class_teacher__staff__user_id=user.pk),
            "activitystudent": Q(activity__class_teacher__staff__user_id=user.pk),
            "assessment": Q(class_teacher__staff__user_id=user.pk),
            "studentassessment": Q(assessment__class_teacher__staff__user_id=user.pk),
            "assessmentimage": Q(student_assessment__assessment__class_teacher__staff__user_id=user.pk),
            "feetype": Q(branch_id=branch_id),
            "feetypeclass": Q(fee_type__branch_id=branch_id),
            "user": Q(pk=user.pk),
        }
        return queryset.filter(scopes[name]).distinct() if name in scopes else queryset.none()

    # Non-teaching staff and principals are limited to their own branch.
    branch_filters = {
        "staff": Q(branch_id=branch_id),
        "branch": Q(pk=branch_id),
        "school": Q(branches__id=branch_id),
        "class": Q(branch_id=branch_id),
        "classteacher": Q(class_obj__branch_id=branch_id),
        "classstudent": Q(class_obj__branch_id=branch_id),
        "student": Q(branch_id=branch_id) | Q(class_students__class_obj__branch_id=branch_id),
        "studentguardian": Q(student__branch_id=branch_id) | Q(student__class_students__class_obj__branch_id=branch_id),
        "guardian": Q(student_guardians__student__branch_id=branch_id) | Q(student_guardians__student__class_students__class_obj__branch_id=branch_id),
        "academicyear": Q(branch_id=branch_id),
        "feetype": Q(branch_id=branch_id),
        "feetypeclass": Q(fee_type__branch_id=branch_id),
        "studentinvoice": Q(class_student__class_obj__branch_id=branch_id),
        "payment": Q(student_invoice__class_student__class_obj__branch_id=branch_id),
        "paymentproof": Q(payment__student_invoice__class_student__class_obj__branch_id=branch_id),
        "activity": Q(class_obj__branch_id=branch_id),
        "activityimage": Q(activity__class_obj__branch_id=branch_id),
        "activitystudent": Q(activity__class_obj__branch_id=branch_id),
        "assessment": Q(class_obj__branch_id=branch_id),
        "studentassessment": Q(assessment__class_obj__branch_id=branch_id),
        "assessmentimage": Q(student_assessment__assessment__class_obj__branch_id=branch_id),
        "user": Q(staff__branch_id=branch_id),
    }
    return queryset.filter(branch_filters[name]).distinct() if name in branch_filters else queryset.none()


class ScopedQuerysetMixin:
    """Scope list/detail querysets and related-object inputs to the request user."""

    def get_queryset(self):
        queryset = super().get_queryset()
        return scope_queryset(queryset, self.request.user)

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        self._scope_related_fields(serializer)
        return serializer

    def _scope_related_fields(self, serializer):
        fields = getattr(serializer, "fields", {})
        for field in fields.values():
            queryset = getattr(field, "queryset", None)
            if queryset is not None:
                field.queryset = scope_queryset(queryset, self.request.user)
            related_child = getattr(field, "child_relation", None)
            related_queryset = getattr(related_child, "queryset", None)
            if related_queryset is not None:
                related_child.queryset = scope_queryset(
                    related_queryset,
                    self.request.user,
                )
            child = getattr(field, "child", None)
            if child is not None and hasattr(child, "fields"):
                self._scope_related_fields(child)
            if hasattr(field, "fields"):
                self._scope_related_fields(field)


def user_can_access_media(user, file_key):
    """Return whether a file key is referenced by a record visible to user."""
    from apps.activities.models import ActivityImage
    from apps.assessments.models import AssessmentImage
    from apps.guardians.models import Guardian
    from apps.payments.models import PaymentProof
    from apps.schools.models import School
    from apps.students.models import Student

    for model in (Student, Guardian, School, ActivityImage, AssessmentImage, PaymentProof):
        visible_records = scope_queryset(model.objects.all(), user)
        if visible_records.filter(image_data__id=file_key).exists():
            return True
    return False
