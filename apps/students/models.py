from django.db import models

from apps.guardians.models import Guardian


class Student(models.Model):
    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("inactive", "Inactive"),
        ("active", "Active"),
        ("out", "Out"),
        ("graduated", "Graduated"),
    ]

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100)
    nickname = models.CharField(max_length=100, blank=True, null=True)

    date_of_birth = models.DateField()

    image_data = models.TextField(blank=True, null=True)

    gender = models.CharField(
        max_length=20,
        choices=GENDER_CHOICES,
    )

    address = models.TextField(blank=True, null=True)

    location_id = models.IntegerField(
        blank=True,
        null=True,
    )

    enroll_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="ACTIVE",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "students"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class StudentGuardian(models.Model):
    RELATIONSHIP_CHOICES = [
        ("father", "Father"),
        ("mother", "Mother"),
        ("grandfather", "Grandfather"),
        ("grandmother", "Grandmother"),
        ("uncle", "Uncle"),
        ("aunt", "Aunt"),
        ("other", "Other"),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="student_guardians",
    )

    guardian = models.ForeignKey(
        Guardian,
        on_delete=models.CASCADE,
        related_name="student_guardians",
    )

    relationship = models.CharField(
        max_length=30,
        choices=RELATIONSHIP_CHOICES,
    )

    is_primary = models.BooleanField(
        default=False,
    )

    class Meta:
        db_table = "student_guardians"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "guardian"],
                name="unique_student_guardian",
            ),
        ]

    def __str__(self):
        return (
            f"{self.student} - "
            f"{self.guardian} "
            f"({self.relationship})"
        )