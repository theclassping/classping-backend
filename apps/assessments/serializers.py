import logging

from rest_framework import serializers

from apps.uploads.serializers import resolve_image_input
from .models import AssessmentImage

logger = logging.getLogger(__name__)


class AssessmentImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = AssessmentImage
        fields = [
            "id",
            "student_assessment",
            "image_data",
            "image_url",
            "caption",
        ]
        read_only_fields = [
            "id",
            "image_url",
        ]

    def get_image_url(self, obj):
        """Get the full URL for the assessment image if metadata exists."""
        return obj.image_url

    def validate(self, attrs):
        """Process image_data if provided."""
        if attrs.get('image_data'):
            attrs['image_data'] = resolve_image_input(self, attrs['image_data'])

        return attrs
