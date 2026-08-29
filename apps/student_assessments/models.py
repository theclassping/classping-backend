from django.db import models

from apps.assessments.models import Assessment
from apps.level_scores.models import LevelScore
from apps.students.models import Student


class StudentAssessment(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="student_assessments",
        db_column="student_id",
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="student_assessments",
        db_column="assessment_id",
    )

    caption = models.TextField(
        blank=True,
    )

    numeric_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    level_score = models.ForeignKey(
        LevelScore,
        on_delete=models.SET_NULL,
        related_name="student_assessments",
        db_column="level_score_id",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "student_assessments"

        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "student"],
                name="unique_student_assessment",
            )
        ]

    def __str__(self):
        return f"{self.student} - {self.assessment}"