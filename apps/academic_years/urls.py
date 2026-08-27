from rest_framework.routers import DefaultRouter

from .views import AcademicYearViewSet


router = DefaultRouter()

router.register(
    "academic-years",
    AcademicYearViewSet,
    basename="academic-years",
)

urlpatterns = router.urls