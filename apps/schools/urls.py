from rest_framework.routers import DefaultRouter

from .views import BranchViewSet, SchoolViewSet

router = DefaultRouter()

router.register("schools", SchoolViewSet, basename="schools")
router.register("branches", BranchViewSet, basename="branches")

urlpatterns = router.urls