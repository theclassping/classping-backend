from django import template
from django.conf import settings
from apps.uploads.services.media import MediaService

register = template.Library()

@register.filter
def admin_image_url(obj):
    if getattr(settings, "STORAGE_TYPE", "local") == "local":
        return getattr(obj, "image_url", None)
    metadata = getattr(obj, "image_data", None) or {}
    file_key = metadata.get("object_key") or metadata.get("id")
    if not file_key:
        return None
    try:
        return MediaService.generate_download_url(file_key, expires_in=3600)
    except Exception:
        return None
