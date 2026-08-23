from datetime import datetime, timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.generics import GenericAPIView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from .models import RevokedAccessToken

from .serializers import (
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer, 
    LogoutSerializer,
    ForgotPasswordSerializer, 
    ResetPasswordSerializer,
    ChangePasswordSerializer
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

class LogoutView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

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
    
class ForgotPasswordView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ForgotPasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception = True)

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(
                email__iexact=email,
                is_active=True,
            )
        except User.DoesNotExist:
            return Response(
                {
                    "detail": (
                        "If an account exists with this email, "
                        "a password reset link has been sent."
                    )
                },
                status=status.HTTP_200_OK,
            )

        uid = urlsafe_base64_encode(
            force_bytes(user.pk)
        )

        token = default_token_generator.make_token(user)

        reset_url = (
            f"http://localhost:3000/reset-password/"
            f"?uid={uid}&token={token}"
        )

        send_mail(
            subject="ClassPing Password Reset",
            message=(
                f"Click the link below to reset your password:\n\n"
                f"{reset_url}\n\n"
                f"If you did not request this, ignore this email."
            ),
            from_email=None,
            recipient_list=[user.email],
        )

        return Response(
            {
                "detail": (
                    "If an account exists with this email, "
                    "a password reset link has been sent."
                )
            },
            status=status.HTTP_200_OK,
        )
    
    
class ResetPasswordView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ResetPasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]

        try:
            user_id = force_str(
                urlsafe_base64_decode(uid)
            )

            user = User.objects.get(
                pk=user_id,
                is_active=True,
            )

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "Invalid password reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(
            user,
            token,
        ):
            return Response(
                {"detail": "Invalid or expired password reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )