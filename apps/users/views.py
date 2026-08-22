from datetime import datetime, timezone
from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from .models import RevokedAccessToken

from .serializers import (
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer
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

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        access_token = request.auth

        if access_token:
            jti = access_token.get("jti")
            exp = access_token.get("exp")

            RevokedAccessToken.objects.get_or_create(
                jti=jti,
                defaults={
                    "expires_at": datetime.fromtimestamp(
                        exp,
                        tz=timezone.utc,
                    )
                },
            )

        refresh_token = request.data.get("refresh")

        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                pass

        return Response(
            {"detail": "Successfully logged out."},
            status=status.HTTP_205_RESET_CONTENT,
        )