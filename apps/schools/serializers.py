from rest_framework import serializers

from apps.locations.models import Location
from apps.locations.serializers import LocationSerializer
from apps.uploads.services.media import MediaService
from .models import Branch, School


class BranchSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = [
            "id",
            "school",
            "name",
            "code",
            "address",
            "phone",
            "email",
            "is_active",
            "location_id",
            "location",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def get_location(self, obj):
        if not obj.location_id:
            return None

        location = Location.objects.filter(pk=obj.location_id).first()

        if not location:
            return None

        return LocationSerializer(location).data


class SchoolSerializer(serializers.ModelSerializer):
    branches = BranchSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = [
            "id",
            "name",
            "register_number",
            "image_data",
            "image_url",
            "is_active",
            "branches",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "image_url",
            "created_at",
            "updated_at",
        ]
    
    def get_image_url(self, obj):
        """Get the full URL for the school's image if metadata exists."""
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