"""
Guards that keep the manual payment flow and the payment gateway apart.

Views (API and admin web) call these; no gateway rules live in views,
serializers or forms.
"""

from django.utils import timezone

from apps.payment_gateway.selectors import get_active_checkout_for_invoice
from apps.student_invoices.models import StudentInvoice

from .exceptions import GatewayPaymentReadOnly, InvoiceLocked
from .models import Payment


def is_gateway_payment(payment):
    # payment_channel and gateway_payment_id always agree (DB check constraint).
    return getattr(payment, "payment_channel", None) == Payment.PaymentChannel.PAYMENT_GATEWAY


def ensure_payment_is_manual(payment):
    """Gateway payment rows are created and changed only by the gateway."""
    if is_gateway_payment(payment):
        raise GatewayPaymentReadOnly()


def ensure_invoice_open_for_manual_payment(invoice):
    """Reject manual payment while the invoice is locked by a gateway checkout."""
    checkout = get_active_checkout_for_invoice(getattr(invoice, "pk", invoice))
    if checkout is not None:
        until = timezone.localtime(checkout.expires_at).strftime("%H:%M")
        raise InvoiceLocked(
            "Invoice sedang dalam pembayaran online sampai {} WIB. "
            "Batalkan checkout pembayaran online untuk mencatat pembayaran manual.".format(until)
        )


def lock_invoice_for_manual_payment(invoice):
    """Row-lock the invoice, then ensure it is open for manual payment.

    Call inside transaction.atomic(). Gateway checkout locks invoices the same
    way, so a manual payment and a checkout for the same invoice are
    serialized instead of racing.
    """
    invoice_id = getattr(invoice, "pk", invoice)
    StudentInvoice.objects.select_for_update().get(pk=invoice_id)
    ensure_invoice_open_for_manual_payment(invoice_id)
