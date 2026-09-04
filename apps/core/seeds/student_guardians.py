from apps.students.models import Student
from apps.guardians.models import Guardian
from apps.students.models import StudentGuardian


def seed_student_guardians():
    guardian = Guardian.objects.get(
        email="john@example.com"
    )

    ethan = Student.objects.get(
        first_name="Ethan",
        last_name="Doe",
    )

    emma = Student.objects.get(
        first_name="Emma",
        last_name="Doe",
    )

    StudentGuardian.objects.get_or_create(
        student=ethan,
        guardian=guardian,
        defaults={
            "relationship": "father",
            "is_primary": True,
        },
    )

    StudentGuardian.objects.get_or_create(
        student=emma,
        guardian=guardian,
        defaults={
            "relationship": "father",
            "is_primary": True,
        },
    )