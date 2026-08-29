from django.db import models

from apps.schools.models import Branch


class ReportLayout(models.Model):
    name = models.CharField(max_length=100)

    description = models.TextField(
        blank=True,
    )

    is_system = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="report_layouts",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "report_layouts"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="unique_report_layout_per_branch",
            )
        ]

    def __str__(self):
        return self.name