from rest_framework.routers import DefaultRouter

from .views import FeeTypeViewSet


router = DefaultRouter()

router.register(
    "fee-types",
    FeeTypeViewSet,
    basename="fee-type",
)

urlpatterns = router.urls