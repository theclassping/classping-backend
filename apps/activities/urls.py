from rest_framework.routers import DefaultRouter

from .views import ActivityViewSet, ActivityImageViewSet, ActivityStudentViewSet

router = DefaultRouter()

router.register(
    "activities",
    ActivityViewSet,
    basename="activities",
)

router.register(
    "activity-images",
    ActivityImageViewSet,
    basename="activity-images",
)

router.register(
    "activity-students",
    ActivityStudentViewSet,
    basename="activity-students",
)

urlpatterns = router.urls
