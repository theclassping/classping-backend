from datetime import date

from apps.users.models import User
from apps.staffs.models import Staff
from apps.schools.models import Branch


def seed_staffs():
    branch = Branch.objects.get(
        name="Main Campus"
    )

    teacher_user = User.objects.get(
        email="anna@classping.test",
        role=User.Role.TEACHER,
    )

    Staff.objects.get_or_create(
        user=teacher_user,
        defaults={
            "staff_type": Staff.StaffType.TEACHER,
            "branch": branch,
            "first_name": teacher_user.first_name,
            "last_name": teacher_user.last_name,
            "email": teacher_user.email,
            "phone": "0221234567",
            "hire_date": date(2026, 1, 1),
            "qualification": (
                "Bachelor of Early Childhood Education"
            ),
        },
    )

    staff_user = User.objects.get(
        email="sam@classping.test",
        role=User.Role.STAFF,
    )

    Staff.objects.get_or_create(
        user=staff_user,
        defaults={
            "staff_type": Staff.StaffType.OFFICER,
            "branch": branch,
            "first_name": staff_user.first_name,
            "last_name": staff_user.last_name,
            "email": staff_user.email,
            "phone": "0221234568",
            "hire_date": date(2026, 1, 1),
            "qualification": "Bachelor of Administration",
        },
    )