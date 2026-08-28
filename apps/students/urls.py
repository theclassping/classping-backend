from rest_framework.routers import DefaultRouter

from .views import StudentViewSet, StudentGuardianViewSet

router = DefaultRouter()

router.register(
    "students",
    StudentViewSet,
    basename="students",
)

router.register(
    "student-guardians",
    StudentGuardianViewSet,
    basename="student-guardians",
)

urlpatterns = router.urls