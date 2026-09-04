from apps.schools.models import School


def seed_schools():
    schools = [
        {
            "name": "ClassPing Preschool",
            "register_number": "CP-2026-001",
        },
        {
            "name": "KB Bintang Kecil",
            "register_number": "CP-2026-002",
        },
    ]

    for data in schools:
        School.objects.get_or_create(
            register_number=data["register_number"],
            defaults=data,
        )