from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    GatewayChannelView,
    GatewayCheckoutView,
    GatewayInvoiceView,
    GatewayPaymentViewSet,
)

router = DefaultRouter()
router.register("gateway/payments", GatewayPaymentViewSet, basename="gateway-payment")

urlpatterns = [
    path("gateway/invoices/", GatewayInvoiceView.as_view(), name="gateway-invoices"),
    path("gateway/channels/", GatewayChannelView.as_view(), name="gateway-channels"),
    path("gateway/checkout/", GatewayCheckoutView.as_view(), name="gateway-checkout"),
] + router.urls
