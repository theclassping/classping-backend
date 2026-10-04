from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)
from rest_framework_simplejwt.views import TokenObtainPairView
from apps.users.serializers import LoginTokenSerializer


class LoginTokenView(TokenObtainPairView):
    serializer_class = LoginTokenSerializer
from apps.users.views import (
    LogoutView,
    ForgotPasswordView,
    ResetPasswordView,
    ChangePasswordView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # OpenAPI schema
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),

    # Swagger UI
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),

    # ReDoc
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    path(
        "api/auth/login/",
        LoginTokenView.as_view(),
        name="token_obtain_pair",
    ),

    path(
        "api/auth/logout/",
        LogoutView.as_view(),
        name="logout",
    ),

    path(
        "api/auth/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),
    
    path(
        "api/auth/forgot-password/",
        ForgotPasswordView.as_view(),
        name="forgot-password",
    ),
    path(
        "api/auth/reset-password/",
        ResetPasswordView.as_view(),
        name="reset-password",
    ),
    path(
        "api/auth/change-password/",
        ChangePasswordView.as_view(),
        name="change-password",
    ),

    path("api/", include("apps.users.urls")),
    path("api/", include("apps.schools.urls")),
    path("api/", include("apps.locations.urls")),
    path("api/", include("apps.staffs.urls")),
    path("api/", include("apps.academic_years.urls")),
    path("api/", include("apps.classes.urls")),
    path("api/", include("apps.students.urls")),
    path("api/", include("apps.guardians.urls")),
    path("api/", include("apps.assessments.urls")),
    path("api/", include("apps.fee_types.urls")),
    path("api/", include("apps.student_invoices.urls")),
    path("api/", include("apps.payments.urls")),
    path("api/", include("apps.activities.urls")),
    path("api/media/", include("apps.uploads.urls")),

    # ClassPing Admin Web
    path(
        "admin-web/",
        include("apps.admin_web.urls"),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
