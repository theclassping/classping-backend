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

    # Sent to the provider as its transaction reference (Rintisan partner_trx_id).
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
    channel_code = models.CharField(max_length=30)
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
    payment_link = models.URLField(max_length=1000, blank=True, default="")
    billing_url = models.URLField(max_length=1000, blank=True, default="")
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
        from apps.payment_aggregator.exceptions import ChannelNotAvailable

        try:
            return PaymentAggregator.get_channel(self.channel_code).name
        except ChannelNotAvailable:
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
