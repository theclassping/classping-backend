"""
Serializers for media uploads and responses.
"""
from rest_framework import serializers


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
    content_type = serializers.CharField(max_length=100, default='application/octet-stream')
    expires_in = serializers.IntegerField(default=3600, min_value=60, max_value=86400)


class PresignUrlResponseSerializer(serializers.Serializer):
    """Serializer for presign URL response."""
    file_key = serializers.CharField()
    presigned_url = serializers.CharField()
    expires_in = serializers.IntegerField()
    content_type = serializers.CharField()
