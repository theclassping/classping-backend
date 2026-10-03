from rest_framework import permissions, viewsets
from apps.users.permissions import RoleBasedAccessPermission

from .models import AcademicYear
from .serializers import AcademicYearSerializer


class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    permission_classes = [
        RoleBasedAccessPermission
    ]