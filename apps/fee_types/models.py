from django.db import models

from apps.schools.models import Branch
from apps.classes.models import Class


class FeeType(models.Model):

    class RecurringFrequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUALLY = "annually", "Annually"

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="fee_types",
    )

    name = models.CharField(
        max_length=100,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=10,
        default="IDR",
    )

    is_recurring = models.BooleanField(
        default=False,
    )

    recurring_frequency = models.CharField(
        max_length=20,
        choices=RecurringFrequency.choices,
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "fee_types"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="unique_fee_type_per_branch",
            )
        ]

    def __str__(self):
        return self.name


class FeeTypeClass(models.Model):
    fee_type = models.ForeignKey(
        FeeType,
        on_delete=models.CASCADE,
        related_name="fee_type_classes",
    )

    class_obj = models.ForeignKey(
        Class,
        on_delete=models.CASCADE,
        related_name="fee_type_classes",
        db_column="class_id",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = "fee_type_classes"
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["fee_type", "class_obj"],
                name="unique_fee_type_class",
            )
        ]

    def __str__(self):
        return f"{self.fee_type.name} - {self.class_obj.name}"