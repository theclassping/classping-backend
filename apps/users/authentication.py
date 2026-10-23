from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import RevokedAccessToken, RevokedTokenSession


class CustomJWTAuthentication(JWTAuthentication):

    def authenticate(self, request):
        result = super().authenticate(request)

        if result is None:
            return None

        user, token = result

        sid = token.get("sid")
        if not sid or RevokedTokenSession.objects.filter(sid=sid).exists():
            raise AuthenticationFailed("Session has been revoked. Please log in again.")

        jti = token.get("jti")

        if jti and RevokedAccessToken.objects.filter(
            jti=jti
        ).exists():
            raise AuthenticationFailed("Token has been revoked.")

        return user, token
