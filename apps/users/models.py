from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models, router, transaction
from django.utils import timezone

from .managers import UserManager


API_MODULE_CHOICES = (
    ("academic_years", "Academic years"),
    ("activities", "Activities"),
    ("assessments", "Assessments"),
    ("classes", "Classes"),
    ("fee_types", "Fee types"),
    ("guardians", "Guardians"),
    ("locations", "Locations"),
    ("payments", "Payments"),
    ("schools", "Schools"),
    ("staffs", "Staff"),
    ("student_invoices", "Student invoices"),
    ("students", "Students"),
    ("uploads", "Media uploads"),
    ("users", "Users"),
)


class User(AbstractBaseUser, PermissionsMixin):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        STAFF = "STAFF", "Staff"
        TEACHER = "TEACHER", "Teacher"
        PARENT = "PARENT", "Parent"

    email = models.EmailField(
        unique=True,
        db_index=True,
    )

    first_name = models.CharField(
        max_length=100,
    )

    last_name = models.CharField(
        max_length=100,
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
    )

    is_active = models.BooleanField(
        default=True,
    )

    is_staff = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        default=timezone.now,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    objects = UserManager()

    def save(self, *args, **kwargs):
        """Invalidate refresh tokens atomically on every persisted password change.

        Keeping this here also covers admin forms and management commands.
        Password writes must use save(), rather than QuerySet.update().
        """
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        update_fields = kwargs.get("update_fields")
        checks_password = update_fields is None or "password" in update_fields
        with transaction.atomic(using=using):
            previous = None
            if self.pk and checks_password:
                previous = type(self).objects.using(using).select_for_update().filter(
                    pk=self.pk
                ).values_list("password", flat=True).first()
            result = super().save(*args, **kwargs)
            if previous is not None and previous != self.password:
                from rest_framework_simplejwt.token_blacklist.models import (
                    BlacklistedToken, OutstandingToken,
                )
                tokens = OutstandingToken.objects.using(using).filter(user_id=self.pk)
                BlacklistedToken.objects.using(using).bulk_create(
                    [BlacklistedToken(token_id=pk) for pk in tokens.values_list("pk", flat=True)],
                    ignore_conflicts=True,
                )
            return result

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class RoleModulePermission(models.Model):
    role = models.CharField(max_length=20, choices=User.Role.choices)
    module = models.CharField(max_length=40, choices=API_MODULE_CHOICES)
    can_read = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        db_table = "user_role_permissions"
        constraints = [
            models.UniqueConstraint(
                fields=("role", "module"),
                name="unique_role_module_permission",
            )
        ]
        ordering = ("role", "module")

    def __str__(self):
        return f"{self.get_role_display()} - {self.get_module_display()}"


class RevokedAccessToken(models.Model):
    jti = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.jti


class RevokedTokenSession(models.Model):
    sid = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
