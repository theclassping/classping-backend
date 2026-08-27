from rest_framework import permissions, viewsets

from .models import Staff
from .serializers import StaffSerializer


class StaffViewSet(viewsets.ModelViewSet):
    queryset = Staff.objects.select_related(
        "branch",
        "branch__school",
    ).all()

    serializer_class = StaffSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]