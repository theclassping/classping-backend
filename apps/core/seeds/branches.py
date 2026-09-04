from apps.schools.models import School, Branch
from apps.locations.models import Location


def seed_branches():
    school = School.objects.get(
        register_number="CP-2026-001"
    )

    location = Location.objects.get(
        code="3273060001"
    )

    branches = [
        {
            "name": "Main Campus",
            "code": "MAIN",
            "email": "main@classping.test",
            "phone": "0221234567",
            "address": "Jl. Lingkar Selatan No. 1",
            "location_id": location.pk,
        },
        {
            "name": "North Campus",
            "code": "NORTH",
            "email": "north@classping.test",
            "phone": "0227654321",
            "address": "Jl. Lengkong Utara No. 10",
            "location_id": location.pk,
        },
    ]

    for data in branches:
        Branch.objects.get_or_create(
            school=school,
            code=data["code"],
            defaults=data,
        )