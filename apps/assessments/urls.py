from rest_framework.routers import DefaultRouter

from .views import AssessmentImageViewSet

router = DefaultRouter()

router.register(
    "assessment-images",
    AssessmentImageViewSet,
    basename="assessment-images",
)

urlpatterns = router.urls
