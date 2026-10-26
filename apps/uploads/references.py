"""Database ownership checks shared by media cleanup paths."""
from django.apps import apps

from apps.uploads.utils import MediaFieldMixin


MEDIA_MODELS = (
    "schools.School", "students.Student", "guardians.Guardian",
    "activities.ActivityImage", "assessments.AssessmentImage",
    "payments.PaymentProof",
)


def is_media_referenced(file_key):
    # Parse legacy JSON strings as well as dictionaries. Use the base manager
    # so records hidden by a default manager still protect their files.
    for label in MEDIA_MODELS:
        model = apps.get_model(label)
        values = model._base_manager.values_list("image_data", flat=True)
        for value in values.iterator():
            data = MediaFieldMixin._parse_media_data(value)
            if isinstance(data, dict) and file_key in (data.get("id"), data.get("object_key")):
                return True
    return False
