from rest_framework import viewsets

from .models import ActivityStudent
from .serializers import ActivityStudentSerializer


class ActivityStudentViewSet(viewsets.ModelViewSet):
    queryset = ActivityStudent.objects.select_related(
        "activity",
        "student",
    ).all()

    serializer_class = ActivityStudentSerializer
