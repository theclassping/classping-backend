from rest_framework.routers import DefaultRouter

from .views import (
    ClassViewSet,
    ClassTeacherViewSet,
    ClassStudentViewSet
)


router = DefaultRouter()

router.register(
    "classes",
    ClassViewSet,
    basename="classes",
)

router.register(
    "class-teachers",
    ClassTeacherViewSet,
    basename="class-teachers",
)

router.register(
    "class-students",
    ClassStudentViewSet,
    basename="class-students",
)

urlpatterns = router.urls