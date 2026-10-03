from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
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