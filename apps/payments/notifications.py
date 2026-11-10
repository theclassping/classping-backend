"""
Payment status emails to the student's primary guardian (Mailjet templates).

Shared by the manual payments API (PaymentSerializer) and the payment
gateway (one payment_completed email per invoice when a checkout is paid).
"""

from django.conf import settings
from django.utils import timezone

from apps.mailer.services import Mailer

from .models import Payment

STATUS_TEMPLATES = {
    Payment.Status.SUBMITTED: "payment_submitted",
    Payment.Status.COMPLETED: "payment_completed",
    Payment.Status.REJECTED: "payment_rejected",
}


def send_payment_status_email(payment):
    template_key = STATUS_TEMPLATES.get(payment.status)
    if not template_key:
        return

    template_id = settings.MAILJET_TEMPLATES[template_key]
    student = payment.student_invoice.class_student.student
    guardian_assignment = student.student_guardians.filter(is_primary=True).select_related("guardian__user").first()
    if not guardian_assignment:
        return

    guardian = guardian_assignment.guardian
    recipient_name = guardian.name or guardian.user.full_name

    Mailer().send_template(
        to_email=guardian.user.email,
        to_name=recipient_name,
        template_id=template_id,
        variables={
            # Mail templates address the recipient as {{name}}.
            "name": recipient_name,
            "student_name": student.full_name(),
            "amount": str(payment.amount),
            "status": payment.status,
            "rejection_reason": payment.rejection_reason or "",
            "invoice_no": payment.student_invoice.invoice_no,
            "updated_at": (
                timezone.localtime(payment.updated_at).strftime("%d %B %Y, %H:%M")
                if payment.updated_at else ""
            ),
            "due_date": (
                payment.student_invoice.due_date.strftime("%d %B %Y")
                if payment.student_invoice.due_date else ""
            ),
        },
    )
