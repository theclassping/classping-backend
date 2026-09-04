from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("score_settings", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="NumericScore",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "min_score",
                            models.DecimalField(
                                decimal_places=2,
                                max_digits=10,
                            ),
                        ),
                        (
                            "max_score",
                            models.DecimalField(
                                decimal_places=2,
                                max_digits=10,
                            ),
                        ),
                        (
                            "score_setting",
                            models.OneToOneField(
                                db_column="score_setting_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="numeric_score",
                                to="score_settings.scoresetting",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "numeric_scores",
                    },
                ),
                migrations.CreateModel(
                    name="LevelScore",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "position",
                            models.PositiveIntegerField(),
                        ),
                        (
                            "name",
                            models.CharField(max_length=100),
                        ),
                        (
                            "score_setting",
                            models.ForeignKey(
                                db_column="score_setting_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="level_scores",
                                to="score_settings.scoresetting",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "level_scores",
                        "ordering": ["score_setting", "position"],
                    },
                ),
                migrations.AddConstraint(
                    model_name="levelscore",
                    constraint=models.UniqueConstraint(
                        fields=("score_setting", "position"),
                        name="unique_level_score_position",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="levelscore",
                    constraint=models.UniqueConstraint(
                        fields=("score_setting", "name"),
                        name="unique_level_score_name",
                    ),
                ),
            ],
        ),
    ]