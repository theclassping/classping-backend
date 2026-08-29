from django.db import models

from apps.activities.models import Activity
from apps.students.models import Student


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