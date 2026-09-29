import secrets

from django.contrib.auth.base_user import BaseUserManager


def generate_temporary_password():
    return secrets.token_urlsafe(18)


class UserManager(BaseUserManager):
    def create_user(
        self,
        email,
        password=None,
        temporary_password=None,
        **extra_fields,
    ):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)

        if temporary_password is not None:
            password = temporary_password

        user = self.model(
            email=email,
            **extra_fields,
        )

        if temporary_password is not None:
            user._temporary_password = temporary_password

        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", self.model.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(
            email=email,
            password=password,
            **extra_fields,
        )