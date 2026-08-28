from django.db import models

from apps.schools.models import Branch


class FeeType(models.Model):
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

    is_recurring = models.BooleanField(
        default=False,
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