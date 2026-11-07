"""Query helpers for reading students together with their relations."""

from django.db.models import Prefetch

from apps.classes.models import ClassStudent

from .models import StudentGuardian


def with_student_relations(queryset):
    """Prefetch what StudentSerializer/StudentDetailSerializer render.

    Guardian links (with guardian and the guardian's own links, used by the
    detail serializer) and class assignments (with the class, its branch
    and academic year) load in a fixed number of queries for any number of
    students.
    """
    return queryset.prefetch_related(
        Prefetch(
            "student_guardians",
            queryset=StudentGuardian.objects.select_related("guardian").prefetch_related(
                "guardian__student_guardians",
            ),
        ),
        Prefetch(
            "class_students",
            queryset=ClassStudent.objects.select_related(
                "class_obj__branch",
                "class_obj__academic_year",
            ),
        ),
    )
