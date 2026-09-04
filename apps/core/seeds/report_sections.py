from apps.report_layouts.models import ReportLayout
from apps.report_sections.models import ReportSection


def seed_report_sections():
    personal_development = ReportLayout.objects.get(name="Personal Development")
    montessori_progress = ReportLayout.objects.get(name="Montessori Progress")

    sections = [
        {"report_layout": personal_development, "name": "Social Emotional"},
        {"report_layout": personal_development, "name": "Communication"},
        {"report_layout": montessori_progress, "name": "Practical Life"},
        {"report_layout": montessori_progress, "name": "Sensorial"},
        {"report_layout": montessori_progress, "name": "Language"},
    ]

    for data in sections:
        ReportSection.objects.get_or_create(
            report_layout=data["report_layout"],
            name=data["name"],
        )
