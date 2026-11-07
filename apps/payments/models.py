from django.db import models
from django.db.models import Q

from apps.payment_aggregator.base import PaymentMethod as GatewayMethod
from apps.student_invoices.models import StudentInvoice
from apps.staffs.models import Staff


class Payment(models.Model):

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    class PaymentMethod(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CASH = "cash", "Cash"
        # Gateway methods (values defined once, in payment_aggregator.base);
        # set only by payment_gateway services.
        VIRTUAL_ACCOUNT = GatewayMethod.VIRTUAL_ACCOUNT, "Virtual Account"
        CREDIT_CARD = GatewayMethod.CREDIT_CARD, "Credit Card"
        E_COMMERCE = GatewayMethod.E_COMMERCE, "E-commerce"

    class PaymentChannel(models.TextChoices):
        MANUAL = "manual", "Manual"
        PAYMENT_GATEWAY = "payment_gateway", "Payment Gateway"

    # Methods staff/parents may use through the existing payments API.
    MANUAL_PAYMENT_METHODS = (
        PaymentMethod.BANK_TRANSFER,
        PaymentMethod.CASH,
    )
    GATEWAY_PAYMENT_METHODS = (
        PaymentMethod.VIRTUAL_ACCOUNT,
        PaymentMethod.CREDIT_CARD,
        PaymentMethod.E_COMMERCE,
    )

    @classmethod
    def method_choices(cls, methods):
        """(value, label) choices for a subset of PaymentMethod."""
        return [(value, label) for value, label in cls.PaymentMethod.choices if value in methods]

    student_invoice = models.OneToOneField(
        StudentInvoice,
        on_delete=models.CASCADE,
        related_name="payment",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )

    payment_channel = models.CharField(
        max_length=20,
        choices=PaymentChannel.choices,
        default=PaymentChannel.MANUAL,
    )

    gateway_payment = models.ForeignKey(
        "payment_gateway.GatewayPayment",
        on_delete=models.PROTECT,
        related_name="payments",
        blank=True,
        null=True,
    )

    submitted_at = models.DateTimeField(
        auto_now_add=True,
    )

    paid_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    verified_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    verified_by = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        related_name="verified_payments",
        blank=True,
        null=True,
    )

    rejection_reason = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "payments"
        ordering = ["-submitted_at"]
        constraints = [
            # Gateway rows always point to their checkout; manual rows never do.
            models.CheckConstraint(
                check=(
                    Q(payment_channel="payment_gateway", gateway_payment__isnull=False)
                    | Q(payment_channel="manual", gateway_payment__isnull=True)
                ),
                name="payment_channel_matches_gateway_payment",
            ),
        ]

    def __str__(self):
        return f"Payment {self.id} - {self.student_invoice.invoice_no}"


class PaymentProof(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="proofs",
    )

    image_data = models.JSONField(
        help_text="Uploaded image metadata (e.g. R2 file key, URL, original name)",
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = "payment_proofs"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Proof {self.id} - Payment {self.payment_id}"
