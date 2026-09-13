"""
Services for generating recurring student invoices.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.fee_types.models import FeeType
from apps.classes.models import ClassStudent
from .models import StudentInvoice


def get_billing_date(fee_type: FeeType, reference_date: date = None) -> date:
    """
    Return the billing date (1st day of the current period) for a recurring fee.
    """
    if reference_date is None:
        reference_date = timezone.now().date()

    if fee_type.recurring_frequency == FeeType.RecurringFrequency.MONTHLY:
        return reference_date.replace(day=1)

    if fee_type.recurring_frequency == FeeType.RecurringFrequency.QUARTERLY:
        quarter_month = ((reference_date.month - 1) // 3) * 3 + 1
        return reference_date.replace(month=quarter_month, day=1)

    if fee_type.recurring_frequency == FeeType.RecurringFrequency.ANNUALLY:
        return reference_date.replace(month=1, day=1)

    return reference_date


def get_due_date(invoice_date: date) -> date:
    """Return a default due date (14 days after invoice date) for MVP."""
    return invoice_date + timedelta(days=14)


def generate_invoice_number(fee_type: FeeType, class_student: ClassStudent, invoice_date: date) -> str:
    """Generate a unique invoice number."""
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return (
        f"INV-{fee_type.branch_id}-"
        f"{class_student.student_id}-{fee_type.id}-"
        f"{invoice_date.strftime('%Y%m%d')}-{timestamp}"
    )


def generate_recurring_invoices(reference_date: date = None):
    """
    Generate invoices for all active recurring fee types for the current billing period.
    """
    if reference_date is None:
        reference_date = timezone.now().date()

    recurring_fees = FeeType.objects.filter(
        is_active=True,
        is_recurring=True,
        recurring_frequency__isnull=False,
    ).prefetch_related(
        "fee_type_classes",
        "fee_type_classes__class_obj",
    )

    created_count = 0

    for fee_type in recurring_fees:
        invoice_date = get_billing_date(fee_type, reference_date)
        due_date = get_due_date(invoice_date)

        fee_classes = fee_type.fee_type_classes.all()

        # If no classes are explicitly linked, skip for safety.
        if not fee_classes:
            continue

        class_ids = [fc.class_obj_id for fc in fee_classes]

        class_students = ClassStudent.objects.filter(
            class_obj_id__in=class_ids,
            is_current=True,
        ).select_related(
            "student",
            "class_obj",
        )

        for class_student in class_students:
            invoice_no = generate_invoice_number(fee_type, class_student, invoice_date)

            _, created = StudentInvoice.objects.get_or_create(
                class_student=class_student,
                fee_type=fee_type,
                invoice_date=invoice_date,
                defaults={
                    "fee_type_class": _resolve_fee_type_class(fee_type, class_student),
                    "invoice_no": invoice_no,
                    "due_date": due_date,
                    "subtotal": fee_type.amount,
                    "total_amount": fee_type.amount,
                    "currency": fee_type.currency,
                    "tax_amount": Decimal("0.00"),
                    "total_discount": Decimal("0.00"),
                    "amount_paid": Decimal("0.00"),
                },
            )

            if created:
                created_count += 1

    return created_count


def _resolve_fee_type_class(fee_type: FeeType, class_student: ClassStudent):
    """Return the FeeTypeClass linker for the student's class, if any."""
    fee_class = fee_type.fee_type_classes.filter(
        class_obj_id=class_student.class_obj_id,
    ).first()

    return fee_class