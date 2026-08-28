from django.db import models
from apps.classes.models import ClassStudent


class StudentInvoice(models.Model):

    class FeeType(models.TextChoices):
        MONTHLY_TUITION = "monthly_tuition", "Monthly Tuition"
        REGISTRATION = "registration", "Registration"
        DEVELOPMENT = "development", "Development"
        EXTRACURRICULAR = "extracurricular", "Extracurricular"
        FIELD_TRIP = "field_trip", "Field Trip"
        SCHOOL_EVENT = "school_event", "School Event"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partial"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    class_student = models.ForeignKey(
        ClassStudent,
        on_delete=models.PROTECT,
        related_name="invoices",
    )

    fee_type = models.CharField(
        max_length=30,
        choices=FeeType.choices,
    )

    invoice_no = models.CharField(
        max_length=50,
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
        max_length=3,
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.invoice_no