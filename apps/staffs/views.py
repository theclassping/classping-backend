from rest_framework import permissions, viewsets
from django.db.models import Q
from apps.users.permissions import RoleBasedAccessPermission

from .models import Staff
from .serializers import StaffSerializer


class StaffViewSet(viewsets.ModelViewSet):
    queryset = Staff.objects.select_related(
        "branch",
        "branch__school",
    ).all()

    serializer_class = StaffSerializer

    permission_classes = [
        RoleBasedAccessPermission
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search))
        branch_id = self.request.query_params.get("branch_id")
        user_id = self.request.query_params.get("user_id") or self.request.query_params.get("user")
        staff_type = self.request.query_params.get("staff_type")
        is_active = self.request.query_params.get("is_active")
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        if staff_type:
            queryset = queryset.filter(staff_type=staff_type)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")
        return queryset
