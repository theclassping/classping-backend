"""
Thin views: access check -> service call -> render. No business rules here.
Every endpoint is limited to the branch principal / officer.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.core.pagination import LIST_FILTER_BACKENDS

from . import services
from .models import LedgerEntry, PayoutAccount, Withdrawal
from .permissions import WithdrawalAccessPermission
from .serializers import (
    LedgerEntryDetailSerializer,
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

    @extend_schema(responses=WalletSerializer)
    def get(self, request):
        return Response(WalletSerializer(services.get_wallet_summary(request.user)).data)


class LedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """C3 GET wallet/ledger/ (ledger columns only) · C3b GET wallet/ledger/{id}/
    (with the gateway payment or withdrawal nested)"""

    permission_classes = [WithdrawalAccessPermission]
    filter_backends = LIST_FILTER_BACKENDS
    filter_fields = {"entry_type": "entry_type", "settlement_status": "settlement_status"}
    date_filter_field = "created_at"
    search_fields = [
        "note",
        "gateway_payment__student__first_name",
        "gateway_payment__student__last_name",
        "gateway_payment__items__student_invoice__invoice_no",
    ]
    ordering_fields = ["created_at", "amount"]
    ordering = ["-created_at", "-pk"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI generation
            return LedgerEntry.objects.none()
        queryset = services.ledger_queryset(self.request.user)
        if self.action == "retrieve":
            queryset = services.ledger_detail_queryset(queryset)
        return queryset

    def get_serializer_class(self):
        return LedgerEntryDetailSerializer if self.action == "retrieve" else LedgerEntrySerializer


class PayoutAccountViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """C4 GET payout-accounts/ (saved accounts to choose from)"""

    permission_classes = [WithdrawalAccessPermission]
    serializer_class = PayoutAccountSerializer
    filter_backends = LIST_FILTER_BACKENDS
    filter_fields = {"bank_code": "bank_code"}
    search_fields = ["account_number", "account_holder_name"]
    ordering_fields = ["updated_at", "created_at"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI generation
            return PayoutAccount.objects.none()
        return services.payout_account_queryset(self.request.user)


class WithdrawalPreviewView(APIView):
    """C7 POST withdrawals/preview/ (emails the OTP to the branch)"""

    permission_classes = [WithdrawalAccessPermission]
    throttle_classes = [WithdrawalOtpThrottle]

    @extend_schema(request=WithdrawalPreviewRequestSerializer, responses=WithdrawalPreviewSerializer)
    def post(self, request):
        payload = WithdrawalPreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        preview = services.preview_withdrawal(request.user, **payload.validated_data)
        return Response(WithdrawalPreviewSerializer(preview).data)


class WithdrawalOtpResendView(APIView):
    """C8 POST withdrawals/otp/resend/"""

    permission_classes = [WithdrawalAccessPermission]
    throttle_classes = [WithdrawalOtpThrottle]

    @extend_schema(request=OtpResendRequestSerializer, responses=WithdrawalPreviewSerializer)
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
    filter_backends = LIST_FILTER_BACKENDS
    filter_fields = {"status": "status", "needs_review": "needs_review"}
    date_filter_field = "created_at"
    search_fields = ["withdrawal_no", "account_holder_name"]
    ordering_fields = ["created_at", "amount", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI generation
            return Withdrawal.objects.none()
        return services.withdrawal_queryset(self.request.user)

    @extend_schema(request=WithdrawalRequestSerializer, responses={201: WithdrawalSerializer})
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
