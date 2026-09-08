from django.db import models
from django.utils import timezone

from apps.classes.models import Class, ClassTeacher
from apps.students.models import Student
from apps.uploads.utils import MediaFieldMixin


class Activity(models.Model):
    class_teacher = models.ForeignKey(
        ClassTeacher,
        on_delete=models.PROTECT,
        related_name="activities",
        db_column="class_teacher_id",
    )

    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="activities",
        db_column="class_id",
    )

    students = models.ManyToManyField(
        Student,
        through="ActivityStudent",
        related_name="activities",
    )

    name = models.CharField(
        max_length=255,
    )

    description = models.TextField(
        blank=True,
    )

    activity_date = models.DateField()

    is_publish = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "activities"
        ordering = [
            "-activity_date",
            "-created_at",
        ]

    def __str__(self):
        return self.name


class ActivityImage(models.Model, MediaFieldMixin):
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="images",
        db_column="activity_id",
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.SET_NULL,
        related_name="activity_images",
        db_column="student_id",
        null=True,
        blank=True,
    )

    image_data = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Stores media metadata: {id, storage, metadata: {filename, size, mime_type}}"
    )

    caption = models.TextField(
        blank=True,
    )

    position = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "activity_images"
        ordering = [
            "position",
            "id",
        ]

    def __str__(self):
        return f"Image - {self.activity.name}"
    
    @property
    def image_url(self):
        """Get the full URL to access the image."""
        return self.get_image_url()


class ActivityStudent(models.Model):
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="activity_students",
        db_column="activity_id",
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="activity_assignments",
        db_column="student_id",
    )

    position = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "activity_students"

        constraints = [
            models.UniqueConstraint(
                fields=["activity", "student"],
                name="unique_activity_student",
            )
        ]

    def __str__(self):
        return f"{self.activity.name} - {self.student}"