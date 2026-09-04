from rest_framework import serializers

from .models import Location


class LocationBreadcrumbSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="location_type")

    class Meta:
        model = Location
        fields = [
            "id",
            "name",
            "code",
            "type",
            "level",
        ]


class LocationSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="location_type")

    parent_id = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=Location.objects.all(),
        required=False,
        allow_null=True,
    )

    path = serializers.SerializerMethodField()

    class Meta:
        model = Location
        fields = [
            "id",
            "name",
            "code",
            "type",
            "parent_id",
            "level",
            "path",
        ]

    def get_path(self, obj):
        # Full breadcrumb from root ancestor down to this location.
        return LocationBreadcrumbSerializer(
            obj.get_ancestors(include_self=True),
            many=True,
        ).data
