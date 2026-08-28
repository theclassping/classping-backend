import os

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create or update the ClassPing development superadmin"

    def handle(self, *args, **options):
        User = get_user_model()

        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            self.stdout.write(
                self.style.ERROR(
                    "DJANGO_SUPERUSER_EMAIL and "
                    "DJANGO_SUPERUSER_PASSWORD are required."
                )
            )
            return

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": "ClassPing",
                "last_name": "Admin",
                "role": User.Role.ADMIN,
                "is_active": True,
                "is_staff": True,
                "is_superuser": True,
            },
        )

        user.set_password(password)
        user.role = User.Role.ADMIN
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save()

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Superadmin created: {email}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Superadmin updated: {email}"
                )
            )