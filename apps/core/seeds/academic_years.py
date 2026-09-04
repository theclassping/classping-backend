from datetime import date

from apps.schools.models import Branch
from apps.academic_years.models import AcademicYear


def seed_academic_years():
    branch = Branch.objects.get(name="Main Campus")

    academic_years = [
        {
            "name": "2025/2026",
            "start_date": date(2025, 7, 1),
            "end_date": date(2026, 6, 30),
            "is_current": False,
        },
        {
            "name": "2026/2027",
            "start_date": date(2026, 7, 1),
            "end_date": date(2027, 6, 30),
            "is_current": True,
        },
    ]

    for data in academic_years:
        AcademicYear.objects.get_or_create(
            branch=branch,
            name=data["name"],
            defaults=data,
        )
