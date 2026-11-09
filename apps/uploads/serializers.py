"""
Serializers for media uploads and responses.
"""
from django.conf import settings
from rest_framework import serializers

import logging

from rest_framework import status
from rest_framework.exceptions import APIException

from apps.uploads.paths import PURPOSE_CATEGORIES
from apps.uploads.services.media import (
    ALLOWED_IMAGE_TYPES,
    MediaInputError,
    MediaService,
    UploadStoreUnavailable,
)

logger = logging.getLogger(__name__)


class ServiceUnavailable(APIException):
    """503: the request was fine but a dependency (Redis) is down; retry it."""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Upload service is temporarily unavailable. Please try again shortly."
    default_code = "service_unavailable"


def resolve_image_input(serializer, value, as_field=True):
    """
    Validate client-supplied image_data (a file_key, URL or metadata dict)
    and return the metadata to store. Use this for every image_data a client
    can send; see MediaService.resolve_image_data for the rules.

    as_field=True raises errors keyed by "image_data", for use in validate().
    """
    if not value:
        return value

    def fail(message):
        raise serializers.ValidationError({"image_data": message} if as_field else message)

    request = serializer.context.get("request")
    try:
        return MediaService.resolve_image_data(value, getattr(request, "user", None))
    except FileNotFoundError:
        fail("File not found. Upload the image first, then send its file_key.")
    except MediaInputError as error:
        fail(str(error))
    except UploadStoreUnavailable:
        # 503, not 400: the request is fine and can be retried as-is.
        raise ServiceUnavailable()
    except Exception:
        logger.exception("Failed to process image_data")
        fail("Error processing image.")


class MediaMetadataSerializer(serializers.Serializer):
    """Serializer for media metadata."""
    filename = serializers.CharField()
    size = serializers.IntegerField()
    mime_type = serializers.CharField()


class MediaSerializer(serializers.Serializer):
    """Serializer for complete media object."""
    id = serializers.CharField()
    storage = serializers.CharField()
    metadata = MediaMetadataSerializer()


class PresignUrlSerializer(serializers.Serializer):
    """Serializer for presign URL request."""
    filename = serializers.CharField(max_length=255)
    content_type = serializers.ChoiceField(
        choices=sorted(ALLOWED_IMAGE_TYPES),
        error_messages={"invalid_choice": "Unsupported file type. Upload a JPEG, PNG, WebP, GIF or HEIC image."},
    )
    # Exact byte size of the file; the upload URL is signed for it.
    size = serializers.IntegerField(min_value=1)
    expires_in = serializers.IntegerField(default=3600, min_value=60, max_value=86400)
    # What the image is for; the server picks the branch/class folder from it.
    purpose = serializers.ChoiceField(choices=sorted(PURPOSE_CATEGORIES))
    class_id = serializers.IntegerField(min_value=1, required=False)
    branch_id = serializers.IntegerField(min_value=1, required=False)

    def validate_size(self, value):
        limit = settings.MAX_UPLOAD_BYTES
        if value > limit:
            raise serializers.ValidationError(
                f"File is too large. Maximum size is {limit // (1024 * 1024)} MB."
            )
        return value


class PresignUrlResponseSerializer(serializers.Serializer):
    """Serializer for presign URL response."""
    file_key = serializers.CharField()
    presigned_url = serializers.CharField()
    expires_in = serializers.IntegerField()
    content_type = serializers.CharField()
