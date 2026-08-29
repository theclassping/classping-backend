from django.db import models

from apps.report_sections.models import ReportSection
from apps.score_settings.models import ScoreSetting


class Indicator(models.Model):
    title = models.CharField(
        max_length=255,
    )

    description = models.TextField(
        blank=True,
    )

    report_section = models.ForeignKey(
        ReportSection,
        on_delete=models.CASCADE,
        related_name="indicators",
        db_column="report_section_id",
    )

    score_setting = models.ForeignKey(
        ScoreSetting,
        on_delete=models.PROTECT,
        related_name="indicators",
        db_column="score_setting_id",
    )

    class Meta:
        db_table = "indicators"
        ordering = ["report_section", "title"]

        constraints = [
            models.UniqueConstraint(
                fields=["report_section", "title"],
                name="unique_indicator_per_report_section",
            )
        ]

    def __str__(self):
        return self.title