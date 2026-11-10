"""Database ownership checks shared by media cleanup paths."""
from django.apps import apps
from django.db.models import Q


MEDIA_MODELS = (
    "schools.School", "students.Student", "guardians.Guardian",
    "activities.ActivityImage", "assessments.AssessmentImage",
    "payments.PaymentProof",
)


def media_key_filter(file_key):
    """Match records whose image_data names file_key under either key field."""
    return Q(image_data__id=file_key) | Q(image_data__object_key=file_key)


def is_media_referenced(file_key):
    # Uses the base manager so records hidden by a default manager still
    # protect their files. Relies on image_data being stored as a JSON object;
    # uploads migration 0002 converted older JSON-string rows.
    for label in MEDIA_MODELS:
        model = apps.get_model(label)
        if model._base_manager.filter(media_key_filter(file_key)).exists():
            return True
    return False
