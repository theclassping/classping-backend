from rest_framework import permissions, viewsets
from django.db.models import Q
from apps.users.permissions import RoleBasedAccessPermission

from .models import AcademicYear
from .serializers import AcademicYearSerializer


class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    permission_classes = [
        RoleBasedAccessPermission
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        branch_id = self.request.query_params.get("branch_id")
        is_current = self.request.query_params.get("is_current")
        if search: queryset = queryset.filter(Q(name__icontains=search))
        if branch_id: queryset = queryset.filter(branch_id=branch_id)
        if is_current is not None: queryset = queryset.filter(is_current=is_current.lower() == "true")
        return queryset
