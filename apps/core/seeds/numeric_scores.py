from apps.score_settings.models import ScoreSetting, NumericScore


def seed_numeric_scores():
    score_setting = ScoreSetting.objects.get(name="Numeric Assessment")

    NumericScore.objects.get_or_create(
        score_setting=score_setting,
        defaults={
            "min_score": 0,
            "max_score": 100,
        },
    )
