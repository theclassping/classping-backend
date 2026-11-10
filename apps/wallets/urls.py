from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    LedgerEntryViewSet,
    PayoutAccountViewSet,
    WalletView,
    WithdrawalOtpResendView,
    WithdrawalPreviewView,
    WithdrawalViewSet,
)

router = DefaultRouter()
router.register("wallet/ledger", LedgerEntryViewSet, basename="wallet-ledger")
router.register("payout-accounts", PayoutAccountViewSet, basename="payout-account")
router.register("withdrawals", WithdrawalViewSet, basename="withdrawal")

urlpatterns = [
    path("wallet/", WalletView.as_view(), name="wallet"),
    path("withdrawals/preview/", WithdrawalPreviewView.as_view(), name="withdrawal-preview"),
    path("withdrawals/otp/resend/", WithdrawalOtpResendView.as_view(), name="withdrawal-otp-resend"),
] + router.urls
