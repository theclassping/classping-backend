from django.db import models

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