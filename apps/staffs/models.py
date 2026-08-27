from django.db import models

from apps.schools.models import Branch


class Staff(models.Model):

    class StaffType(models.TextChoices):
        PRINCIPAL = "principal", "Principal"
        TEACHER = "teacher", "Teacher"
        OFFICER = "officer", "Officer"

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="staffs",
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=50, blank=True)

    staff_type = models.CharField(
        max_length=20,
        choices=StaffType.choices,
    )

    hire_date = models.DateField()
    qualification = models.CharField(max_length=225)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staffs"
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"