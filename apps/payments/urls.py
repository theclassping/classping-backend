from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PaymentProofViewSet, PaymentViewSet


router = DefaultRouter()

router.register(
    "payments",
    PaymentViewSet,
    basename="payment",
)

router.register(
    "payment-proofs",
    PaymentProofViewSet,
    basename="payment-proof",
)

urlpatterns = router.urls