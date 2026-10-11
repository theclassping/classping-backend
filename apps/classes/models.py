from django.db import models, transaction
from django.core.exceptions import ValidationError

from apps.schools.models import Branch
from apps.staffs.models import Staff
from apps.students.models import Student
from apps.academic_years.models import AcademicYear


class Class(models.Model):
    name = models.CharField(max_length=100)

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="classes",
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="classes",
    )

    teachers = models.ManyToManyField(
        Staff,
        through="ClassTeacher",
        related_name="classes",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "school_brach_classes"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["branch", "academic_year", "name"],
                name="unique_class_per_branch_academic_year",
            )
        ]

    def __str__(self):
        return self.name
    
class ClassTeacher(models.Model):
    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="class_teachers",
        db_column="class_id",
    )

    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="class_teaching_assignments",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "class_teachers"

        constraints = [
            models.UniqueConstraint(
                fields=["class_obj", "staff"],
                name="unique_class_teacher",
            )
        ]

    def clean(self):
        if self.staff.staff_type != Staff.StaffType.TEACHER:
            raise ValidationError(
                "Only staff with teacher type can be assigned to a class."
            )

    def __str__(self):
        return f"{self.class_obj.name} - {self.staff}"
    

class ClassStudent(models.Model):
    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="class_students",
        db_column="class_id",
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="class_students",
    )

    is_current = models.BooleanField(
        default=False,
        help_text="Only one class should be marked as current per student",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "class_students"

        constraints = [
            models.UniqueConstraint(
                fields=["class_obj", "student"],
                name="unique_class_student",
            ),
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(is_current=True),
                name="unique_current_class_per_student",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.is_current:
            with transaction.atomic():
                type(self).objects.filter(
                    student_id=self.student_id,
                    is_current=True,
                ).exclude(pk=self.pk).update(is_current=False)
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    @classmethod
    def ensure_current_for_student(cls, student):
        """Keep active students assigned to exactly one current class."""
        if student.status != "active":
            return None
        current = cls.objects.filter(student=student, is_current=True).first()
        if current:
            return current
        latest = cls.objects.filter(student=student).order_by("-created_at", "-pk").first()
        if latest:
            latest.is_current = True
            latest.save(update_fields=["is_current"])
        return latest

    def __str__(self):
        return f"{self.class_obj.name} - {self.student}"
