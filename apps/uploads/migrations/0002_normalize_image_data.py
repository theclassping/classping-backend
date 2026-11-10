"""
Convert image_data values stored as JSON *strings* ("{\"id\": ...}") into
JSON objects, so file keys can be found with database lookups such as
image_data__id=<key> instead of scanning every row in Python.

Strings that don't hold a JSON object are left alone: the app already
treats them as "no image", so changing them would change behaviour.
"""
import json

from django.db import migrations

MEDIA_MODELS = (
    ("schools", "School"),
    ("students", "Student"),
    ("guardians", "Guardian"),
    ("activities", "ActivityImage"),
    ("assessments", "AssessmentImage"),
    ("payments", "PaymentProof"),
)


def normalize_image_data(apps, schema_editor):
    for app_label, model_name in MEDIA_MODELS:
        model = apps.get_model(app_label, model_name)
        rows = model._base_manager.exclude(image_data=None).values_list("pk", "image_data")
        for pk, value in rows.iterator():
            if not isinstance(value, str):
                continue
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                # update() skips save signals, so no media cleanup runs here.
                model._base_manager.filter(pk=pk).update(image_data=parsed)


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0001_initial"),
        ("schools", "0004_remove_branch_location_id_branch_location"),
        ("students", "0007_student_branch"),
        ("guardians", "0003_alter_guardian_image_data"),
        ("activities", "0007_activityimage_client_id"),
        ("assessments", "0003_alter_assessmentimage_image_data"),
        ("payments", "0001_initial"),
    ]

    # Nothing to undo: an object holds the same data as the string did.
    operations = [
        migrations.RunPython(normalize_image_data, migrations.RunPython.noop),
    ]
