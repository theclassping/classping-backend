from rest_framework import serializers

from apps.uploads.services.media import MediaService
from .models import AssessmentImage


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
        if 'image_data' in attrs and attrs['image_data']:
            image_data_input = attrs['image_data']
            if isinstance(image_data_input, str):
                try:
                    processed_metadata = MediaService.process_image_data(image_data_input)
                    attrs['image_data'] = processed_metadata
                except FileNotFoundError:
                    raise serializers.ValidationError({
                        "image_data": "File not found. Please provide the full file path, e.g. 'C:/Users/audia/Downloads/brownies.jpg'"
                    })
                except Exception as e:
                    raise serializers.ValidationError({
                        "image_data": f"Error processing image: {str(e)}"
                    })

        return attrs
