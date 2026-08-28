from django.db import models

from apps.classes.models import ClassStudent
from apps.fee_types.models import FeeType


class StudentInvoice(models.Model):

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partial"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    class_student = models.ForeignKey(
        ClassStudent,
        on_delete=models.PROTECT,
        related_name="invoices",
    )

    fee_type = models.ForeignKey(
        FeeType,
        on_delete=models.PROTECT,
        related_name="student_invoices",
    )

    invoice_no = models.CharField(
        max_length=100,
        unique=True,
    )

    invoice_date = models.DateField()

    due_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNPAID,
    )

    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=10,
        default="IDR",
    )

    total_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    remark = models.TextField(
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
        db_table = "student_invoices"
        ordering = ["-invoice_date"]

    def __str__(self):
        return self.invoice_no