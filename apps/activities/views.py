from rest_framework import viewsets

from .models import Activity, ActivityImage, ActivityStudent
from .serializers import (
    ActivitySerializer,
    ActivityImageSerializer,
    ActivityStudentSerializer,
)


class ActivityViewSet(viewsets.ModelViewSet):
    queryset = Activity.objects.select_related(
        "class_obj",
        "class_teacher",
    ).prefetch_related(
        "images",
        "activity_students__student",
    ).all()

    serializer_class = ActivitySerializer
    

class ActivityImageViewSet(viewsets.ModelViewSet):
    queryset = ActivityImage.objects.select_related(
        "activity",
        "student",
    ).all()

    serializer_class = ActivityImageSerializer


class ActivityStudentViewSet(viewsets.ModelViewSet):
    queryset = ActivityStudent.objects.select_related(
        "activity",
        "student",
    ).all()

    serializer_class = ActivityStudentSerializer
