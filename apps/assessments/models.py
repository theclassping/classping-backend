from django.db import models

from apps.classes.models import Class, ClassTeacher


class Assessment(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="assessments",
        db_column="class_id",
    )

    name = models.CharField(
        max_length=255,
    )

    start_date = models.DateField()

    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    class_teacher = models.ForeignKey(
        ClassTeacher,
        on_delete=models.PROTECT,
        related_name="assessments",
        db_column="class_teacher_id",
    )

    class Meta:
        db_table = "assessments"
        ordering = ["-start_date"]

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}

        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                errors["end_date"] = (
                    "End date must be greater than or equal to start date."
                )

        if (
            self.class_teacher_id
            and self.class_obj_id
            and self.class_teacher.class_obj_id
            != self.class_obj_id
        ):
            errors["class_teacher"] = (
                "The class teacher must belong to the selected class."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name