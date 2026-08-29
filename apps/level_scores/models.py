from django.db import models
from django.core.exceptions import ValidationError

from apps.score_settings.models import ScoreSetting


class LevelScore(models.Model):
    score_setting = models.ForeignKey(
        ScoreSetting,
        on_delete=models.CASCADE,
        related_name="level_scores",
        db_column="score_setting_id",
    )

    position = models.PositiveIntegerField()

    name = models.CharField(
        max_length=100,
    )

    class Meta:
        db_table = "level_scores"
        ordering = ["score_setting", "position"]

        constraints = [
            models.UniqueConstraint(
                fields=["score_setting", "position"],
                name="unique_level_score_position",
            ),

            models.UniqueConstraint(
                fields=["score_setting", "name"],
                name="unique_level_score_name",
            ),
        ]

    def clean(self):
        if (
            self.score_setting.score_type
            != ScoreSetting.ScoreType.LEVEL
        ):
            raise ValidationError(
                "LevelScore can only be used with level score type."
            )

    def __str__(self):
        return f"{self.position}. {self.name}"