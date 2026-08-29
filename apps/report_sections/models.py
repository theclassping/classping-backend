from django.db import models

from apps.report_layouts.models import ReportLayout


class ReportSection(models.Model):
    name = models.CharField(max_length=100)

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    report_layout = models.ForeignKey(
        ReportLayout,
        on_delete=models.CASCADE,
        related_name="report_sections",
        db_column="report_layout_id",
    )

    class Meta:
        db_table = "report_sections"
        ordering = ["id"]

        constraints = [
            models.UniqueConstraint(
                fields=["report_layout", "name"],
                name="unique_report_section_per_layout",
            )
        ]

    def __str__(self):
        return self.name