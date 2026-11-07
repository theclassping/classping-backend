"""Read model for the parent web app's dashboard layout."""

from dataclasses import dataclass, field
from typing import List, Optional

from django.http import Http404

from apps.classes.models import Class
from apps.core.access import scope_queryset
from apps.schools.models import Branch, School
from apps.students.models import Student
from apps.students.selectors import with_student_relations


@dataclass
class ParentContext:
    students: List[Student] = field(default_factory=list)
    student: Optional[Student] = None
    current_class: Optional[Class] = None
    branch: Optional[Branch] = None
    school: Optional[School] = None


def get_parent_context(user, student_id=None):
    """Load the guardian's students and the selected student's class, branch, school.

    The selected student is `student_id` when given (Http404 if it is not one
    of the user's students), otherwise the first student in the same order
    as GET /api/students/. The branch is the current class's branch, falling
    back to the student's own branch when there is no current class.
    """
    students = list(with_student_relations(
        scope_queryset(Student.objects.order_by("-id"), user).distinct()
    ))

    if student_id is not None:
        student = next((item for item in students if item.pk == student_id), None)
        if student is None:
            raise Http404("Student not found.")
    elif students:
        student = students[0]
    else:
        return ParentContext()

    current = next((link for link in student.class_students.all() if link.is_current), None)
    current_class = None
    if current is not None:
        current_class = (
            scope_queryset(Class.objects.all(), user)
            .select_related("branch__school", "academic_year")
            .prefetch_related(
                "branch__school__branches",
                "class_students__student",
                "class_teachers__staff",
            )
            .filter(pk=current.class_obj_id)
            .first()
        )

    if current_class is not None:
        branch = current_class.branch
    elif student.branch_id:
        branch = (
            Branch.objects.select_related("school")
            .prefetch_related("school__branches")
            .filter(pk=student.branch_id)
            .first()
        )
    else:
        branch = None

    return ParentContext(
        students=students,
        student=student,
        current_class=current_class,
        branch=branch,
        school=branch.school if branch is not None else None,
    )
