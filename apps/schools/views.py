from rest_framework import permissions, viewsets
from django.db.models import Q
from apps.users.permissions import RoleBasedAccessPermission

from .models import Branch, School
from .serializers import BranchSerializer, SchoolSerializer


class SchoolViewSet(viewsets.ModelViewSet):
    queryset = School.objects.all().order_by("-created_at")
    serializer_class = SchoolSerializer
    permission_classes = [RoleBasedAccessPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(register_number__icontains=search))
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")
        return queryset


class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.select_related("school").all()
    serializer_class = BranchSerializer
    permission_classes = [RoleBasedAccessPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search) | Q(school__name__icontains=search))
        school_id = self.request.query_params.get("school_id")
        is_active = self.request.query_params.get("is_active")
        if school_id:
            queryset = queryset.filter(school_id=school_id)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")
        return queryset
