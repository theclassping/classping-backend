from rest_framework import permissions
from rest_framework import viewsets

from .models import FeeType
from .serializers import FeeTypeSerializer


class FeeTypeViewSet(viewsets.ModelViewSet):

    queryset = FeeType.objects.select_related(
        "branch",
    ).all()

    serializer_class = FeeTypeSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch_id")
        is_active = self.request.query_params.get("is_active")

        if branch_id:
            queryset = queryset.filter(
                branch_id=branch_id
            )

        if is_active is not None:
            queryset = queryset.filter(
                is_active=is_active.lower() == "true"
            )

        return queryset