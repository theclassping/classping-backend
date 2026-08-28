from rest_framework.routers import DefaultRouter

from apps.student_invoices.views import StudentInvoiceViewSet


router = DefaultRouter()

router.register(
    "student-invoices",
    StudentInvoiceViewSet,
    basename="student-invoices",
)

urlpatterns = router.urls