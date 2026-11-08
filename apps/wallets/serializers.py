"""
Input shape validation and output rendering only. Business rules and all
calculations live in services.py / payment_aggregator.
"""

from rest_framework import serializers

from apps.payment_gateway.serializers import GatewayPaymentDetailSerializer

from .models import LedgerEntry, PayoutAccount, Withdrawal

# --- Input ----------------------------------------------------------------


class WithdrawalPreviewRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    # Either a saved account ...
    payout_account_id = serializers.IntegerField(min_value=1, required=False)
    # ... or a new one (saved automatically by the withdrawal).
    bank_code = serializers.CharField(max_length=30, required=False, default="")
    account_number = serializers.RegexField(r"^[0-9]{5,30}$", required=False, default="")
    account_holder_name = serializers.CharField(max_length=100, required=False, default="", trim_whitespace=True)


class OtpResendRequestSerializer(serializers.Serializer):
    otp_reference = serializers.CharField(max_length=64)


class WithdrawalRequestSerializer(serializers.Serializer):
    otp_reference = serializers.CharField(max_length=64)
    otp = serializers.CharField(max_length=10)
    fee_acknowledged = serializers.BooleanField()


# --- Output ---------------------------------------------------------------


class WalletSerializer(serializers.Serializer):
    """Renders services.WalletSummary."""

    branch_id = serializers.IntegerField()
    available_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_count = serializers.IntegerField()
    withdrawn_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    withdrawn_count = serializers.IntegerField()
    withdrawal_fee = serializers.DecimalField(max_digits=14, decimal_places=2)


LEDGER_FIELDS = [
    "id",
    "created_at",
    "entry_type",
    "amount",
    "balance_after",
    "settlement_status",
    "settled_at",
    "gateway_payment_id",
    "withdrawal_id",
    "note",
]


class LedgerEntrySerializer(serializers.ModelSerializer):
    """C3 list: ledger columns only (no joins)."""

    class Meta:
        model = LedgerEntry
        fields = LEDGER_FIELDS
        read_only_fields = fields


class PayoutAccountSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(read_only=True)
    account_number_masked = serializers.CharField(read_only=True)

    class Meta:
        model = PayoutAccount
        fields = ["id", "bank_code", "bank_name", "account_number_masked", "account_holder_name", "updated_at"]
        read_only_fields = fields


class DestinationSerializer(serializers.Serializer):
    bank_code = serializers.CharField()
    bank_name = serializers.CharField()
    account_number_masked = serializers.CharField()
    account_holder_name = serializers.CharField()


class WithdrawalPreviewSerializer(serializers.Serializer):
    """Renders services.WithdrawalPreview (C7 / C8)."""

    otp_reference = serializers.CharField(source="otp.reference")
    otp_sent_to = serializers.EmailField(source="otp.sent_to")
    otp_expires_at = serializers.DateTimeField(source="otp.expires_at")
    amount = serializers.DecimalField(source="breakdown.amount", max_digits=14, decimal_places=2)
    fee = serializers.DecimalField(source="breakdown.fee", max_digits=14, decimal_places=2)
    transfer_amount = serializers.DecimalField(source="breakdown.transfer_amount", max_digits=14, decimal_places=2)
    payout_account = DestinationSerializer(source="otp")


class WithdrawalSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(read_only=True)
    account_number_masked = serializers.CharField(read_only=True)

    class Meta:
        model = Withdrawal
        fields = [
            "id",
            "withdrawal_no",
            "status",
            "amount",
            "fee",
            "transfer_amount",
            "bank_code",
            "bank_name",
            "account_number_masked",
            "account_holder_name",
            "failure_reason",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields


class LedgerEntryDetailSerializer(serializers.ModelSerializer):
    """C3b detail: the entry with its gateway payment or withdrawal nested
    (the same serializers as gateway/payments/{id}/ and withdrawals/{id}/)."""

    gateway_payment = GatewayPaymentDetailSerializer(read_only=True)
    withdrawal = WithdrawalSerializer(read_only=True)

    class Meta:
        model = LedgerEntry
        fields = LEDGER_FIELDS + ["gateway_payment", "withdrawal"]
        read_only_fields = fields
