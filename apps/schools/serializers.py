import logging

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.locations.models import Location
from apps.locations.serializers import (
    LocationPreloadListSerializer,
    LocationSerializer,
    preloaded_location,
)
from apps.uploads.serializers import resolve_image_input
from .models import Branch, School

logger = logging.getLogger(__name__)


class BranchSerializer(serializers.ModelSerializer):
    location_id = serializers.PrimaryKeyRelatedField(
        source="location",
        queryset=Location.objects.all(),
        required=True,
    )
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
            "storage_capacity_bytes",
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
        list_serializer_class = LocationPreloadListSerializer

    def validate_storage_capacity_bytes(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and not (user.is_superuser or str(user.role).upper() == "ADMIN"):
            raise PermissionDenied("Only admins can change a branch's storage capacity.")
        return value

    def get_location(self, obj):
        if not obj.location_id:
            return None

        preloaded, payload = preloaded_location(self, obj.location_id)
        if preloaded:
            return payload

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
        if attrs.get('image_data'):
            attrs['image_data'] = resolve_image_input(self, attrs['image_data'])
        
        return attrs
