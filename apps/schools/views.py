from apps.core.access import ScopedQuerysetMixin
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from django.db.models import Q
from apps.uploads.services import quota
from apps.uploads.usage import branch_storage_report, branches_by_usage
from apps.users.permissions import RoleBasedAccessPermission

from .models import Branch, School
from .serializers import BranchSerializer, SchoolSerializer


class SchoolViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = School.objects.prefetch_related("branches").order_by("-created_at")
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


def can_view_storage(user) -> bool:
    """Admins see every branch; branch staff see their own. Teachers and parents don't."""
    role = str(user.role).upper()
    if user.is_superuser or role == "ADMIN":
        return True
    staff = getattr(user, "staff", None)
    return role == "STAFF" and staff is not None and staff.staff_type != "teacher"


class BranchViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
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

    def _require_storage_access(self):
        if not can_view_storage(self.request.user):
            raise PermissionDenied("You do not have access to storage usage.")

    @action(detail=False, methods=["get"], url_path="storage-usage")
    def storage_usage_list(self, request):
        """Visible branches, fullest (percent of capacity) first."""
        self._require_storage_access()
        return Response(branches_by_usage(self.filter_queryset(self.get_queryset())))

    @action(detail=True, methods=["get"], url_path="storage-usage")
    def storage_usage(self, request, pk=None):
        """One branch's usage, broken down per category and per class."""
        self._require_storage_access()
        return Response(branch_storage_report(self.get_object()))

    # Storage actions use their own role check (can_view_storage) instead of
    # the "schools" module grants, which branch staff don't have for writes.
    # get_object() still limits them to branches the user can see.

    def _storage_branch(self):
        self._require_storage_access()
        return self.get_object()

    @action(detail=True, methods=["post"], url_path="storage-reset", permission_classes=[permissions.IsAuthenticated])
    def storage_reset(self, request, pk=None):
        """
        Clear stored images of one category (optionally one class) to free space.

        Body: {"category": "activities", "class_id": 12, "dry_run": true}
        dry_run (default false) only returns what would be freed.
        Records are kept; only their images are removed. Payment proofs
        cannot be reset.
        """
        branch = self._storage_branch()
        category = request.data.get("category")
        class_id = request.data.get("class_id")
        dry_run = request.data.get("dry_run") in (True, "true", "1", 1)
        if class_id not in (None, ""):
            try:
                class_id = int(class_id)
            except (TypeError, ValueError):
                raise ValidationError({"class_id": "Must be an integer."})
        else:
            class_id = None
        try:
            if dry_run:
                summary = quota.summarize(quota.reset_candidates(branch, category, class_id))
            else:
                summary = quota.reset_branch_media(branch, category, class_id, request.user)
        except quota.StorageActionError as error:
            raise ValidationError({"error": str(error)})
        body = {"category": category, "class_id": class_id, "dry_run": dry_run, **summary}
        return Response(body, status=status.HTTP_200_OK if dry_run else status.HTTP_202_ACCEPTED)
