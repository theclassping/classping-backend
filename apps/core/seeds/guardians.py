from apps.users.models import User
from apps.guardians.models import Guardian


def seed_guardians():
    user = User.objects.get(
        email="john@example.com",
        role=User.Role.PARENT,
    )

    Guardian.objects.get_or_create(
        user=user,
        defaults={
            "name": user.full_name,
            "phone_number": "081234567890",
            "email": user.email,
        },
    )