from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.response import Response

from .serializers import (
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer

        if self.action in ["update", "partial_update"]:
            return UserUpdateSerializer

        return UserSerializer

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()

        # Soft delete instead of permanently deleting the user.
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])

        return Response(
            status=status.HTTP_204_NO_CONTENT,
        )