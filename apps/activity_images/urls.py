from rest_framework.routers import DefaultRouter

from .views import ActivityImageViewSet

router = DefaultRouter()

router.register(
    "activity-images",
    ActivityImageViewSet,
    basename="activity-images",
)

urlpatterns = router.urls
