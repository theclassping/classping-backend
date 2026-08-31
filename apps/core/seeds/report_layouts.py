from apps.schools.models import Branch
from apps.report_layouts.models import ReportLayout


def seed_report_layouts():
    branch = Branch.objects.get(name="Main Campus")

    layouts = [
        {"name": "Personal Development"},
        {"name": "Montessori Progress"},
    ]

    for data in layouts:
        ReportLayout.objects.get_or_create(
            branch=branch,
            name=data["name"],
        )
