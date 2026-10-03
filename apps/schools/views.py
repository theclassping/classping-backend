from rest_framework import permissions, viewsets
from apps.users.permissions import RoleBasedAccessPermission

from .models import Branch, School
from .serializers import BranchSerializer, SchoolSerializer


class SchoolViewSet(viewsets.ModelViewSet):
    queryset = School.objects.all().order_by("-created_at")
    serializer_class = SchoolSerializer
    permission_classes = [RoleBasedAccessPermission]


class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.select_related("school").all()
    serializer_class = BranchSerializer
    permission_classes = [RoleBasedAccessPermission]