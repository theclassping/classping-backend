from django.db import models

from apps.classes.models import Class, ClassTeacher


class Activity(models.Model):
    class_teacher = models.ForeignKey(
        ClassTeacher,
        on_delete=models.PROTECT,
        related_name="activities",
        db_column="class_teacher_id",
    )

    name = models.CharField(
        max_length=255,
    )

    description = models.TextField(
        blank=True,
    )

    activity_date = models.DateField()

    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="activities",
        db_column="class_id",
    )

    class Meta:
        db_table = "activities"
        ordering = ["-activity_date"]

    def clean(self):
        from django.core.exceptions import ValidationError

        if (
            self.class_teacher_id
            and self.class_obj_id
            and self.class_teacher.class_obj_id
            != self.class_obj_id
        ):
            raise ValidationError(
                "The class teacher must belong to the selected class."
            )

    def __str__(self):
        return self.name