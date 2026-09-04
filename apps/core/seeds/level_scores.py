from apps.score_settings.models import ScoreSetting, LevelScore


def seed_level_scores():
    score_setting = ScoreSetting.objects.get(name="Development Level")

    levels = [
        {"position": 1, "name": "Beginning"},
        {"position": 2, "name": "Developing"},
        {"position": 3, "name": "Secure"},
    ]

    for data in levels:
        LevelScore.objects.get_or_create(
            score_setting=score_setting,
            position=data["position"],
            defaults=data,
        )
