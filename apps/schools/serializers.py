from rest_framework import serializers

from apps.locations.models import Location
from apps.locations.serializers import LocationSerializer
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

    class Meta:
        model = School
        fields = [
            "id",
            "name",
            "register_number",
            "is_active",
            "branches",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]