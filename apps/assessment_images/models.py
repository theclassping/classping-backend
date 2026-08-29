from django.db import models

from apps.student_assessments.models import StudentAssessment


class AssessmentImage(models.Model):
    student_assessment = models.ForeignKey(
        StudentAssessment,
        on_delete=models.CASCADE,
        related_name="assessment_images",
        db_column="student_assessment_id",
    )

    image_data = models.ImageField(
        upload_to="assessments/images/",
    )

    caption = models.TextField(
        blank=True,
    )

    class Meta:
        db_table = "assessment_images"

    def __str__(self):
        return (
            f"Image - "
            f"{self.student_assessment.student}"
        )