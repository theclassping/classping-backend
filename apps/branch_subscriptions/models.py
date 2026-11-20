from django.db import models


class SubscriptionPayment(models.Model):
    """
    One online checkout (VA / card) for a subscription invoice.

    Separate from GatewayPayment: that one needs a student and a guardian and
    paying it credits the branch wallet. Subscription money goes to Classping
    and never touches BranchWallet. payment_no starts with "SUB-" so the
    payment webhook can route it here.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    TRANSITIONS = {
        Status.PENDING: {Status.PAID, Status.EXPIRED, Status.CANCELLED, Status.FAILED},
        # A payment confirmed after the window closed still counts.
        Status.EXPIRED: {Status.PAID},
        Status.CANCELLED: {Status.PAID},
        Status.FAILED: {Status.PAID},
        Status.PAID: set(),
    }

    payment_no = models.CharField(max_length=50, unique=True)
    invoice = models.ForeignKey(
        "plan_subscriptions.SubscriptionInvoice", on_delete=models.PROTECT, related_name="online_payments",
    )
    branch = models.ForeignKey("schools.Branch", on_delete=models.PROTECT, related_name="subscription_payments")
    staff = models.ForeignKey(
        "staffs.Staff", null=True, blank=True, on_delete=models.SET_NULL, related_name="subscription_payments",
    )
    provider = models.CharField(max_length=30)
    channel_code = models.CharField(max_length=50)
    channel_name = models.CharField(max_length=100, blank=True)
    payment_method = models.CharField(max_length=30, blank=True)
    invoice_total = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_fee = models.DecimalField(max_digits=14, decimal_places=2)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    provider_trx_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    payment_code = models.CharField(max_length=100, blank=True)
    payment_link = models.TextField(blank=True)
    billing_url = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=100, blank=True)
    expires_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_response = models.JSONField(null=True, blank=True)
    callback_payload = models.JSONField(null=True, blank=True)
    callback_received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscription_payments"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="subscription_payment_idempotency",
            )
        ]

    def __str__(self):
        return self.payment_no

    def can_transition_to(self, status):
        return status in self.TRANSITIONS.get(self.status, set())
