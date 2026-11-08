"""
Thin views: access check -> service call -> render. No business rules here.
Every endpoint is limited to the branch principal / officer.
"""

from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from . import services
from .permissions import WithdrawalAccessPermission
from .serializers import (
    LedgerEntrySerializer,
    OtpResendRequestSerializer,
    PayoutAccountSerializer,
    WalletSerializer,
    WithdrawalPreviewRequestSerializer,
    WithdrawalPreviewSerializer,
    WithdrawalRequestSerializer,
    WithdrawalSerializer,
)


class WithdrawalOtpThrottle(UserRateThrottle):
    scope = "withdrawal_otp"


class WalletView(APIView):
    """C2 GET wallet/"""

    permission_classes = [WithdrawalAccessPermission]

    def get(self, request):
        return Response(WalletSerializer(services.get_wallet_summary(request.user)).data)


class LedgerEntryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """C3 GET wallet/ledger/"""

    permission_classes = [WithdrawalAccessPermission]
    serializer_class = LedgerEntrySerializer

    def get_queryset(self):
        return services.ledger_queryset(self.request.user).select_related("gateway_payment", "withdrawal")


class PayoutAccountViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """C4 GET payout-accounts/ (saved accounts to choose from)"""

    permission_classes = [WithdrawalAccessPermission]
    serializer_class = PayoutAccountSerializer

    def get_queryset(self):
        return services.payout_account_queryset(self.request.user)


class WithdrawalPreviewView(APIView):
    """C7 POST withdrawals/preview/ (emails the OTP to the branch)"""

    permission_classes = [WithdrawalAccessPermission]
    throttle_classes = [WithdrawalOtpThrottle]

    def post(self, request):
        payload = WithdrawalPreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        preview = services.preview_withdrawal(request.user, **payload.validated_data)
        return Response(WithdrawalPreviewSerializer(preview).data)


class WithdrawalOtpResendView(APIView):
    """C8 POST withdrawals/otp/resend/"""

    permission_classes = [WithdrawalAccessPermission]
    throttle_classes = [WithdrawalOtpThrottle]

    def post(self, request):
        payload = OtpResendRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        preview = services.resend_withdrawal_otp(request.user, payload.validated_data["otp_reference"])
        return Response(WithdrawalPreviewSerializer(preview).data)


class WithdrawalViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """C9 POST withdrawals/ · C10 GET withdrawals[/{id}]/"""

    permission_classes = [WithdrawalAccessPermission]
    serializer_class = WithdrawalSerializer

    def get_queryset(self):
        queryset = services.withdrawal_queryset(self.request.user)
        if self.request.query_params.get("status"):
            queryset = queryset.filter(status=self.request.query_params["status"])
        return queryset

    def create(self, request, *args, **kwargs):
        payload = WithdrawalRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        withdrawal = services.create_withdrawal(
            request.user,
            payload.validated_data["otp_reference"],
            payload.validated_data["otp"],
            payload.validated_data["fee_acknowledged"],
        )
        return Response(WithdrawalSerializer(withdrawal).data, status=status.HTTP_201_CREATED)
