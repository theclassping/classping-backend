from celery import shared_task
from django.db import OperationalError
from django.utils import timezone

from apps.payment_aggregator.exceptions import ProviderUnavailable

from . import services
from .models import GatewayPayment


@shared_task(
    bind=True,
    autoretry_for=(ProviderUnavailable, OperationalError),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=5,
)
def expire_gateway_payment_task(self, gateway_payment_id):
    """Queued at checkout for expires_at + delay (the provider sends no expiry callback)."""
    try:
        gateway_payment = services.expire_gateway_payment(gateway_payment_id)
    except GatewayPayment.DoesNotExist:
        return None
    if (
        gateway_payment.status == GatewayPayment.Status.PENDING
        and timezone.now() < gateway_payment.expires_at
    ):
        # Ran early (clock skew): try again after the window.
        raise self.retry(eta=services.expiry_check_time(gateway_payment))
    return gateway_payment.status


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, max_retries=3)
def send_payment_completed_email_task(self, payment_id):
    """payment_completed email for one invoice settled by a gateway checkout
    (one task per invoice, so a retry never resends the others)."""
    from apps.payments.models import Payment
    from apps.payments.notifications import send_payment_status_email

    payment = Payment.objects.select_related("student_invoice__class_student__student").filter(pk=payment_id).first()
    if payment is not None:
        send_payment_status_email(payment)


@shared_task
def reconcile_settlements_task():
    """Hourly: move settled checkouts from pending to available balance."""
    return services.reconcile_settlements()
