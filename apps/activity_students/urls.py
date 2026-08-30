from rest_framework.routers import DefaultRouter

from .views import ActivityStudentViewSet

router = DefaultRouter()

router.register(
    "activity-students",
    ActivityStudentViewSet,
    basename="activity-students",
)

urlpatterns = router.urls
