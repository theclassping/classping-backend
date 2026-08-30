from apps.locations.models import Location


def seed_locations():
    indonesia, _ = Location.objects.get_or_create(
        code="ID",
        defaults={
            "name": "Indonesia",
            "location_type": "COUNTRY",
            "parent": None,
        },
    )

    jawa_barat, _ = Location.objects.get_or_create(
        code="32",
        defaults={
            "name": "Jawa Barat",
            "location_type": "PROVINCE",
            "parent": indonesia,
        },
    )

    kota_bandung, _ = Location.objects.get_or_create(
        code="3273",
        defaults={
            "name": "Kota Bandung",
            "location_type": "CITY",
            "parent": jawa_barat,
        },
    )

    lengkong, _ = Location.objects.get_or_create(
        code="3273060",
        defaults={
            "name": "Lengkong",
            "location_type": "DISTRICT",
            "parent": kota_bandung,
        },
    )

    Location.objects.get_or_create(
        code="3273060001",
        defaults={
            "name": "Lingkar Selatan",
            "location_type": "VILLAGE",
            "parent": lengkong,
        },
    )