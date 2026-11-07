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
        # Full breadcrumb from root ancestor down to this location. Bulk
        # loaders (apps.locations.selectors) pass the ancestors preloaded.
        ancestors = self.context.get("location_ancestors", {}).get(obj.pk)
        if ancestors is None:
            ancestors = obj.get_ancestors(include_self=True)
        return LocationBreadcrumbSerializer(
            ancestors,
            many=True,
        ).data


class LocationPreloadListSerializer(serializers.ListSerializer):
    """List serializer that loads every row's `location` payload in bulk.

    The child serializer reads the result through `preloaded_location()`.
    Payloads are cached on the root serializer so nested lists (for example
    branches inside schools) and sibling fields of a composite serializer
    reuse locations already loaded.
    """

    def to_representation(self, data):
        from django.db.models import Manager

        from .selectors import location_payloads

        items = list(data.all() if isinstance(data, Manager) else data)
        cache = self.root.__dict__.setdefault("_location_payload_cache", {})
        missing = {item.location_id for item in items if item.location_id} - cache.keys()
        if missing:
            payloads = location_payloads(missing)
            cache.update({location_id: payloads.get(location_id) for location_id in missing})
        return super().to_representation(items)


def preloaded_location(serializer, location_id):
    """Return (True, payload) if a list serializer preloaded this location."""
    cache = serializer.root.__dict__.get("_location_payload_cache")
    if cache is None or location_id not in cache:
        return False, None
    return True, cache[location_id]
