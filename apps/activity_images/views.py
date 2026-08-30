from rest_framework import viewsets

from .models import ActivityImage
from .serializers import ActivityImageSerializer


class ActivityImageViewSet(viewsets.ModelViewSet):
    queryset = ActivityImage.objects.select_related(
        "activity",
        "student",
    ).all()

    serializer_class = ActivityImageSerializer
