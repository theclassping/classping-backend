from django.db import models
from django.db.models import F, Q

from apps.payments.models import Payment


class GatewayPayment(models.Model):
    """One gateway checkout: one student, one or more of that student's invoices.

    Status changes happen only through payment_gateway services.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        # The provider billing could not be created; the payer never got
        # payment instructions.
        FAILED = "failed", "Failed"

    # Allowed status changes. PAID is final; a payment confirmed after the
    # checkout was closed still moves it to PAID (late payment, never lost).
    TRANSITIONS = {
        Status.PENDING: {Status.PAID, Status.EXPIRED, Status.CANCELLED, Status.FAILED},
        Status.EXPIRED: {Status.PAID},
        Status.CANCELLED: {Status.PAID},
        Status.FAILED: {Status.PAID},
        Status.PAID: set(),
    }

    def can_transition_to(self, status):
        return status in self.TRANSITIONS.get(self.status, set())

    # Sent to the provider as its transaction reference (DANA partnerReferenceNo).
    payment_no = models.CharField(max_length=50, unique=True)

    branch = models.ForeignKey(
        "schools.Branch",
        on_delete=models.PROTECT,
        related_name="gateway_payments",
    )
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        related_name="gateway_payments",
    )
    # Guardian who started the checkout.
    guardian = models.ForeignKey(
        "guardians.Guardian",
        on_delete=models.PROTECT,
        related_name="gateway_payments",
    )

    provider = models.CharField(max_length=30)
    # Provider channel code, e.g. DOKU "VIRTUAL_ACCOUNT_BANK_SYARIAH_MANDIRI" (36).
    channel_code = models.CharField(max_length=50)
    # Same values as payments.payment_method for gateway rows.
    payment_method = models.CharField(
        max_length=30,
        choices=Payment.method_choices(Payment.GATEWAY_PAYMENT_METHODS),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # invoice_total = sum of items (the branch's share);
    # amount = invoice_total + transaction_fee (what the payer pays).
    invoice_total = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    idempotency_key = models.CharField(max_length=100)

    provider_trx_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    payment_code = models.TextField(blank=True, default="")
    # TextField: Tokopedia/OneLink deep links can exceed 1000 characters.
    payment_link = models.TextField(blank=True, default="")
    billing_url = models.TextField(blank=True, default="")
    provider_response = models.JSONField(blank=True, null=True)
    callback_payload = models.JSONField(blank=True, null=True)
    callback_received_at = models.DateTimeField(blank=True, null=True)

    deadline_date = models.DateField()
    expires_at = models.DateTimeField()
    paid_at = models.DateTimeField(blank=True, null=True)
    settled_at = models.DateTimeField(blank=True, null=True)

    cancelled_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        related_name="cancelled_gateway_payments",
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True, default="")

    # Ops flags: paid after the invoice was already settled elsewhere, or a
    # callback/query did not match (e.g. amount mismatch).
    needs_refund = models.BooleanField(default=False)
    needs_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True, default="")

    # Online refund through the provider (payment_gateway.services.refund_gateway_payment).
    class RefundStatus(models.TextChoices):
        # Branch debited, provider asked; outcome not known yet (retry sends
        # the same refund_no, never a second refund).
        PROCESSING = "processing", "Processing"
        REFUNDED = "refunded", "Refunded"
        # Provider refused; the branch debit was reversed.
        FAILED = "failed", "Failed"

    refund_status = models.CharField(max_length=20, choices=RefundStatus.choices, blank=True, default="")
    # Our refund reference sent to the provider (DANA partnerRefundNo).
    refund_no = models.CharField(max_length=60, unique=True, blank=True, null=True)
    refund_amount = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    refund_provider_id = models.CharField(max_length=100, blank=True, default="")
    refund_reason = models.TextField(blank=True, default="")
    refunded_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        related_name="refunded_gateway_payments",
        blank=True,
        null=True,
    )
    refund_requested_at = models.DateTimeField(blank=True, null=True)
    refunded_at = models.DateTimeField(blank=True, null=True)
    refund_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gateway_payments"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "idempotency_key"],
                name="uniq_gateway_payment_idempotency_per_guardian",
            ),
            models.CheckConstraint(
                check=Q(invoice_total__gt=0),
                name="gateway_payment_invoice_total_positive",
            ),
            models.CheckConstraint(
                check=Q(transaction_fee__gte=0),
                name="gateway_payment_fee_non_negative",
            ),
            models.CheckConstraint(
                check=Q(amount=F("invoice_total") + F("transaction_fee")),
                name="gateway_payment_amount_matches_total_plus_fee",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="gw_payment_status_created"),
            models.Index(fields=["branch", "status"], name="gw_payment_branch_status"),
        ]

    def __str__(self):
        return self.payment_no

    @property
    def channel_name(self):
        """Display name of the channel (falls back to the code if retired)."""
        from apps.payment_aggregator import PaymentAggregator
        from payment_aggregator.exceptions import ChannelNotAvailable, ProviderNotConfigured

        try:
            return PaymentAggregator.using(self.provider).get_channel(self.channel_code).name
        except (ChannelNotAvailable, ProviderNotConfigured):
            return self.channel_code


class GatewayPaymentItem(models.Model):
    """An invoice inside a checkout. While is_active, the invoice is locked."""

    gateway_payment = models.ForeignKey(
        GatewayPayment,
        on_delete=models.CASCADE,
        related_name="items",
    )
    student_invoice = models.ForeignKey(
        "student_invoices.StudentInvoice",
        on_delete=models.PROTECT,
        related_name="gateway_payment_items",
    )
    # Outstanding amount of the invoice at checkout time.
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gateway_payment_items"
        ordering = ["id"]
        constraints = [
            # Anti double-pay: an invoice can be in only one active checkout.
            models.UniqueConstraint(
                fields=["student_invoice"],
                condition=Q(is_active=True),
                name="uniq_active_gateway_item_per_invoice",
            ),
            models.UniqueConstraint(
                fields=["gateway_payment", "student_invoice"],
                name="uniq_gateway_item_invoice_per_payment",
            ),
            models.CheckConstraint(
                check=Q(amount__gt=0),
                name="gateway_payment_item_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.gateway_payment_id} - {self.student_invoice_id}"


class SettlementFile(models.Model):
    """A provider settlement file imported by an admin (audit + reconciliation)."""

    provider = models.CharField(max_length=30)
    file_name = models.CharField(max_length=255)
    # Same content is never imported twice.
    sha256 = models.CharField(max_length=64, unique=True)
    imported_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        related_name="imported_settlement_files",
        blank=True,
        null=True,
    )
    line_count = models.PositiveIntegerField(default=0)
    settled_count = models.PositiveIntegerField(default=0)
    review_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    # Sum of the provider's SETTLE_AMOUNT (what should reach the bank), when given.
    settle_amount_total = models.DecimalField(max_digits=16, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gateway_settlement_files"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.file_name


class SettlementLine(models.Model):
    """One line of a settlement file and what the import did with it."""

    class Result(models.TextChoices):
        SETTLED = "settled", "Settled now"
        ALREADY_SETTLED = "already_settled", "Already settled"
        CHECKED = "checked", "Matches our records"
        AMOUNT_MISMATCH = "amount_mismatch", "Amount mismatch (review)"
        NOT_PAID = "not_paid", "Not paid in Classping (review)"
        REVIEW = "review", "Needs review"
        UNMATCHED = "unmatched", "No matching payment"
        IGNORED = "ignored", "Not used by Classping"

    # Results an admin has to look at.
    REVIEW_RESULTS = (Result.AMOUNT_MISMATCH, Result.NOT_PAID, Result.REVIEW)

    settlement_file = models.ForeignKey(SettlementFile, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    line_type = models.CharField(max_length=20)  # payment_aggregator SettlementLineType
    provider_type = models.CharField(max_length=40, blank=True, default="")
    provider_trx_id = models.CharField(max_length=100, blank=True, default="")
    original_trx_id = models.CharField(max_length=100, blank=True, default="")
    reference_no = models.CharField(max_length=100, blank=True, default="")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    fee = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    settle_amount = models.DecimalField(max_digits=16, decimal_places=2, blank=True, null=True)
    settled_at = models.DateTimeField(blank=True, null=True)
    transaction_at = models.DateTimeField(blank=True, null=True)
    pay_method = models.CharField(max_length=40, blank=True, default="")
    gateway_payment = models.ForeignKey(
        GatewayPayment,
        on_delete=models.SET_NULL,
        related_name="settlement_lines",
        blank=True,
        null=True,
    )
    result = models.CharField(max_length=20, choices=Result.choices)
    note = models.TextField(blank=True, default="")
    raw = models.JSONField(blank=True, default=dict)

    class Meta:
        db_table = "gateway_settlement_lines"
        ordering = ["settlement_file", "line_no"]
        indexes = [models.Index(fields=["provider_trx_id"], name="gw_settle_line_trx")]

    def __str__(self):
        return "{} #{}".format(self.settlement_file_id, self.line_no)

    @property
    def result_label(self):
        return self.get_result_display()
