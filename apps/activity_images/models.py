from django.db import models

from apps.activities.models import Activity
from apps.students.models import Student


class ActivityImage(models.Model):
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

    image_data = models.ImageField(
        upload_to="activities/images/",
    )

    caption = models.TextField(
        blank=True,
    )

    class Meta:
        db_table = "activity_images"

    def __str__(self):
        return f"Image - {self.activity.name}"