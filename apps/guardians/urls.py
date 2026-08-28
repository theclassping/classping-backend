from rest_framework.routers import DefaultRouter

from .views import GuardianViewSet


router = DefaultRouter()

router.register(
    "guardians",
    GuardianViewSet,
    basename="guardians",
)

urlpatterns = router.urls