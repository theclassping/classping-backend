from rest_framework import permissions, viewsets

from .models import AcademicYear
from .serializers import AcademicYearSerializer


class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    permission_classes = [
        permissions.IsAuthenticated
    ]