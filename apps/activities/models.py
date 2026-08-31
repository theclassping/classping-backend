from django.db import models

from apps.classes.models import Class, ClassTeacher
from apps.students.models import Student


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