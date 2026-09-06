from django.db.models import Q
from rest_framework import permissions, viewsets

from .models import Location
from .serializers import LocationSerializer


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LocationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Location.objects.all().order_by("tree_id", "lft")

        parent_id = self.request.query_params.get("parent_id")
        location_type = self.request.query_params.get("type")
        search = self.request.query_params.get("search")

        if parent_id is not None:
            if parent_id.lower() == "null":
                queryset = queryset.filter(parent__isnull=True)
            else:
                queryset = queryset.filter(parent_id=parent_id)

        if location_type:
            queryset = queryset.filter(location_type=location_type.upper())

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(code__icontains=search)
            )

        return queryset