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
    """Queued at checkout for expires_at + delay (backup to the expiry webhook)."""
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
