from django.db import models

from apps.schools.models import Branch


class ScoreSetting(models.Model):

    class ScoreType(models.TextChoices):
        NUMERIC = "numeric", "Numeric"
        LEVEL = "level", "Level"

    name = models.CharField(
        max_length=100,
    )

    description = models.TextField(
        blank=True,
    )

    score_type = models.CharField(
        max_length=20,
        choices=ScoreType.choices,
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="score_settings",
    )

    class Meta:
        db_table = "score_settings"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="unique_score_setting_per_branch",
            )
        ]

    def __str__(self):
        return self.name