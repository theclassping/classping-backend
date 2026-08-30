from rest_framework import viewsets

from .models import Activity
from .serializers import ActivitySerializer


class ActivityViewSet(viewsets.ModelViewSet):
    queryset = Activity.objects.select_related(
        "class_obj",
        "class_teacher",
    ).prefetch_related(
        "images",
        "activity_students__student",
    ).all()

    serializer_class = ActivitySerializer
