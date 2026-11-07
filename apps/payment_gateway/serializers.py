"""
Input shape validation and output rendering only. Business rules and all
calculations live in services.py / payment_aggregator.
"""

from rest_framework import serializers

from apps.payment_aggregator.constants import MAX_INVOICES_PER_CHECKOUT

from .exceptions import InvalidInvoiceIds
from .models import GatewayPayment, GatewayPaymentItem

INVOICE_IDS_MESSAGE = "invoice_ids must contain 1 to {} invoice ids.".format(MAX_INVOICES_PER_CHECKOUT)


def parse_invoice_ids(raw):
    """'11,12' (query string) or [11, 12] (JSON) -> [11, 12]."""
    if isinstance(raw, str):
        raw = [part for part in raw.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        raise InvalidInvoiceIds(INVOICE_IDS_MESSAGE)
    try:
        invoice_ids = [int(value) for value in raw]
    except (TypeError, ValueError):
        raise InvalidInvoiceIds(INVOICE_IDS_MESSAGE)
    if not 1 <= len(set(invoice_ids)) <= MAX_INVOICES_PER_CHECKOUT or len(set(invoice_ids)) != len(invoice_ids):
        raise InvalidInvoiceIds(INVOICE_IDS_MESSAGE)
    return invoice_ids


class CheckoutRequestSerializer(serializers.Serializer):
    invoice_ids = serializers.ListField(child=serializers.IntegerField(min_value=1))
    channel = serializers.CharField(max_length=30)

    def validate_invoice_ids(self, value):
        return parse_invoice_ids(value)


# --- Output ---------------------------------------------------------------


class PayableInvoiceSerializer(serializers.Serializer):
    """Renders services.InvoicePayability."""

    id = serializers.IntegerField(source="invoice.pk")
    invoice_no = serializers.CharField(source="invoice.invoice_no")
    fee_type = serializers.CharField(source="invoice.fee_type.name")
    invoice_date = serializers.DateField(source="invoice.invoice_date")
    due_date = serializers.DateField(source="invoice.due_date")
    status = serializers.CharField(source="invoice.status")
    total_amount = serializers.DecimalField(source="invoice.total_amount", max_digits=12, decimal_places=2)
    payable = serializers.BooleanField()
    not_payable_reason = serializers.CharField(source="reason", allow_null=True)
    locked_until = serializers.DateTimeField(source="locked_by.expires_at", default=None)
    active_gateway_payment_id = serializers.IntegerField(source="locked_by.pk", default=None)


class StudentPayabilitySerializer(serializers.Serializer):
    """Renders services.StudentPayability (B0)."""

    student_id = serializers.IntegerField(source="student.pk")
    student_name = serializers.CharField(source="student.full_name")
    branch_id = serializers.IntegerField(allow_null=True)
    is_payment_gateway_enabled = serializers.BooleanField()
    payment_window_minutes = serializers.IntegerField()
    invoices = PayableInvoiceSerializer(many=True)


class ChannelSerializer(serializers.Serializer):
    """Renders payment_aggregator.base.FeeBreakdown."""

    code = serializers.CharField(source="channel_code")
    name = serializers.CharField(source="channel_name")
    payment_method = serializers.CharField()
    transaction_fee = serializers.DecimalField(max_digits=14, decimal_places=2)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class CheckoutQuoteSerializer(serializers.Serializer):
    """Renders services.CheckoutQuote (B1)."""

    student_id = serializers.IntegerField(source="student.pk")
    branch_id = serializers.IntegerField()
    invoice_ids = serializers.SerializerMethodField()
    invoice_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_window_minutes = serializers.IntegerField()
    expires_at = serializers.DateTimeField()
    channels = ChannelSerializer(many=True)

    def get_invoice_ids(self, quote):
        return [invoice.pk for invoice in quote.invoices]


class GatewayPaymentItemSerializer(serializers.ModelSerializer):
    invoice_no = serializers.CharField(source="student_invoice.invoice_no", read_only=True)
    fee_type = serializers.CharField(source="student_invoice.fee_type.name", read_only=True)

    class Meta:
        model = GatewayPaymentItem
        fields = ["student_invoice_id", "invoice_no", "fee_type", "amount"]


SUMMARY_FIELDS = [
    "id",
    "payment_no",
    "status",
    "student_id",
    "student_name",
    "guardian_id",
    "channel_code",
    "channel_name",
    "payment_method",
    "invoice_total",
    "transaction_fee",
    "amount",
    "expires_at",
    "paid_at",
    "created_at",
]


class GatewayPaymentSummarySerializer(serializers.ModelSerializer):
    """B3 list item (no payment instructions)."""

    student_name = serializers.CharField(source="student.full_name", read_only=True)
    channel_name = serializers.CharField(read_only=True)
    invoice_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = GatewayPayment
        fields = SUMMARY_FIELDS + ["invoice_count"]
        read_only_fields = fields


class GatewayPaymentDetailSerializer(serializers.ModelSerializer):
    """B2 / B4."""

    student_name = serializers.CharField(source="student.full_name", read_only=True)
    channel_name = serializers.CharField(read_only=True)
    items = GatewayPaymentItemSerializer(many=True, read_only=True)

    class Meta:
        model = GatewayPayment
        fields = SUMMARY_FIELDS + [
            "branch_id",
            "payment_code",
            "payment_link",
            "billing_url",
            "items",
        ]
        read_only_fields = fields
