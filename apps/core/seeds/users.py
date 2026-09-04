from apps.users.models import User


def seed_users():
    users = [
        {
            "email": "admin@classping.test",
            "first_name": "System",
            "last_name": "Admin",
            "role": User.Role.ADMIN,
            "is_staff": True,
            "is_superuser": True,
            "password": "password123",
        },
        {
            "email": "anna@classping.test",
            "first_name": "Anna",
            "last_name": "Teacher",
            "role": User.Role.TEACHER,
            "is_staff": False,
            "is_superuser": False,
            "password": "password123",
        },
        {
            "email": "john@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "role": User.Role.PARENT,
            "is_staff": False,
            "is_superuser": False,
            "password": "password123",
        },
    ]

    for data in users:
        password = data.pop("password")

        user, created = User.objects.get_or_create(
            email=data["email"],
            defaults=data,
        )

        if created:
            user.set_password(password)
            user.save()