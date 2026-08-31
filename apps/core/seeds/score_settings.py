from apps.schools.models import Branch
from apps.score_settings.models import ScoreSetting


def seed_score_settings():
    branch = Branch.objects.get(name="Main Campus")

    settings = [
        {
            "name": "Development Level",
            "description": "Level-based scale used to assess student development.",
            "score_type": ScoreSetting.ScoreType.LEVEL,
        },
        {
            "name": "Numeric Assessment",
            "description": "Numeric scale used to assess student performance.",
            "score_type": ScoreSetting.ScoreType.NUMERIC,
        },
    ]

    for data in settings:
        ScoreSetting.objects.get_or_create(
            branch=branch,
            name=data["name"],
            defaults=data,
        )
