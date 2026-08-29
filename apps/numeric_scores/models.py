from django.db import models

from apps.score_settings.models import ScoreSetting


class NumericScore(models.Model):
    score_setting = models.OneToOneField(
        ScoreSetting,
        on_delete=models.CASCADE,
        related_name="numeric_score",
        db_column="score_setting_id",
    )

    min_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    max_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    class Meta:
        db_table = "numeric_scores"

    def clean(self):
        if self.min_score > self.max_score:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                "Minimum score cannot be greater than maximum score."
            )

        if (
            self.score_setting.score_type
            != ScoreSetting.ScoreType.NUMERIC
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError(
                "NumericScore can only be used with numeric score type."
            )

    def __str__(self):
        return (
            f"{self.score_setting.name} "
            f"({self.min_score} - {self.max_score})"
        )