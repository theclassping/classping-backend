from apps.report_sections.models import ReportSection
from apps.score_settings.models import ScoreSetting
from apps.indicators.models import Indicator


def seed_indicators():
    social_emotional = ReportSection.objects.get(
        report_layout__name="Personal Development",
        name="Social Emotional",
    )

    level_setting = ScoreSetting.objects.get(name="Development Level")

    indicators = [
        {"title": "Cooperation"},
        {"title": "Sharing"},
    ]

    for data in indicators:
        Indicator.objects.get_or_create(
            report_section=social_emotional,
            title=data["title"],
            defaults={
                "score_setting": level_setting,
            },
        )
