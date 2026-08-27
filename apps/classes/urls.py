from rest_framework.routers import DefaultRouter

from .views import (
    ClassViewSet,
    ClassTeacherViewSet,
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

urlpatterns = router.urls