"""Test fixtures shared by API performance and parent-portal tests."""

from datetime import date
from decimal import Decimal

from apps.academic_years.models import AcademicYear
from apps.classes.models import Class, ClassStudent
from apps.fee_types.models import FeeType
from apps.guardians.models import Guardian
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student, StudentGuardian
from apps.users.models import RoleModulePermission, User

PARENT_READ_MODULES = ("students", "classes", "schools", "guardians", "student_invoices")


def grant_parent_reads(*modules):
    """Grant PARENT read access to the given modules (as configured in prod)."""
    for module in modules or PARENT_READ_MODULES:
        RoleModulePermission.objects.update_or_create(
            role="PARENT", module=module, defaults={"can_read": True},
        )


def build_family(prefix, children=1, location=None):
    """Create a parent with `children` students, each in its own school/branch/class.

    Every child gets a current class, a previous class and one invoice, and
    every branch and student gets a location with an ancestor, so nested
    location paths are exercised.
    """
    if location is None:
        country = Location.objects.create(name=f"{prefix} Country", code=f"{prefix}C", location_type="COUNTRY")
        location = Location.objects.create(
            name=f"{prefix} Province", code=f"{prefix}P", location_type="PROVINCE", parent=country,
        )
    user = User.objects.create_user(
        email=f"{prefix}-parent@example.test", password="StrongPassword123!", role="PARENT",
    )
    guardian = Guardian.objects.create(user=user, name=f"{prefix} Parent", email=user.email)
    students = []
    for index in range(children):
        tag = f"{prefix}{index}"
        school = School.objects.create(name=f"School {tag}", register_number=f"REG-{tag}")
        branch = Branch.objects.create(school=school, location=location, name=f"Branch {tag}", code=tag)
        year = AcademicYear.objects.create(
            branch=branch, name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        previous = Class.objects.create(branch=branch, academic_year=year, name=f"Previous {tag}")
        current = Class.objects.create(branch=branch, academic_year=year, name=f"Current {tag}")
        student = Student.objects.create(
            first_name="Child", last_name=tag, date_of_birth=date(2019, 1, 1), gender="male",
            enroll_date=date(2026, 1, 1), status="active", branch=branch, location_id=location.pk,
        )
        StudentGuardian.objects.create(student=student, guardian=guardian, relationship="mother", is_primary=True)
        ClassStudent.objects.create(student=student, class_obj=previous, is_current=False)
        class_student = ClassStudent.objects.create(student=student, class_obj=current, is_current=True)
        fee_type = FeeType.objects.create(branch=branch, name=f"SPP {tag}", amount=Decimal("100000"))
        StudentInvoice.objects.create(
            class_student=class_student, fee_type=fee_type, invoice_no=f"INV-{tag}",
            invoice_date=date(2026, 10, 1), due_date=date(2026, 10, 10),
            subtotal=Decimal("100000"), total_amount=Decimal("100000"),
        )
        students.append(student)
    return user, guardian, students
