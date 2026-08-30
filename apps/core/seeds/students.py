from apps.students.models import Student
from apps.locations.models import Location


def seed_students():
    location = Location.objects.get(
        code="3273060001"
    )

    students = [
        {
            "first_name": "Ethan",
            "middle_name": "",
            "last_name": "Doe",
            "nickname": "Ethan",
            "date_of_birth": "2021-05-15",
            "gender": "male",
            "address": "Jl. Lingkar Selatan No. 20",
            "location_id": location.pk,
            "enroll_date": "2026-07-01",
        },
        {
            "first_name": "Emma",
            "middle_name": "",
            "last_name": "Doe",
            "nickname": "Emma",
            "date_of_birth": "2020-08-20",
            "gender": "female",
            "address": "Jl. Lengkong No. 30",
            "location_id": location.pk,
            "enroll_date": "2026-07-01",
        },
    ]

    for data in students:
        Student.objects.get_or_create(
            first_name=data["first_name"],
            last_name=data["last_name"],
            date_of_birth=data["date_of_birth"],
            defaults=data,
        )