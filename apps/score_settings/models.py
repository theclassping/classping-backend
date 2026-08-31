from django.db import models
from django.core.exceptions import ValidationError

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
            raise ValidationError(
                "Minimum score cannot be greater than maximum score."
            )

        if (
            self.score_setting.score_type
            != ScoreSetting.ScoreType.NUMERIC
        ):
            raise ValidationError(
                "NumericScore can only be used with numeric score type."
            )

    def __str__(self):
        return (
            f"{self.score_setting.name} "
            f"({self.min_score} - {self.max_score})"
        )


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

    def __str__(self):
        return self.name