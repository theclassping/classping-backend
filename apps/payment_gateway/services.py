"""
Gateway payment status changes. Every change takes a row lock and re-checks
the status (GatewayPayment.can_transition_to), so the expiry job, provider
webhooks and cancellations can run at the same time without overwriting
each other: the second one to get the lock sees the new status and does
nothing.
"""

import datetime
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator.base import BillingStatus
from apps.payment_aggregator.constants import PAYMENT_EXPIRY_CHECK_DELAY_MINUTES
from apps.payment_aggregator.exceptions import BillingNotFound

from .models import GatewayPayment

logger = logging.getLogger(__name__)


def expiry_check_time(gateway_payment):
    return gateway_payment.expires_at + datetime.timedelta(minutes=PAYMENT_EXPIRY_CHECK_DELAY_MINUTES)


def mark_gateway_payment_expired(gateway_payment_id):
    """PENDING -> EXPIRED and release the invoices (items inactive).

    No-op when another process already changed the status. Used by the
    expiry job and (Step 5) the provider's expiry webhook.
    """
    with transaction.atomic():
        gateway_payment = GatewayPayment.objects.select_for_update().get(pk=gateway_payment_id)
        if not gateway_payment.can_transition_to(GatewayPayment.Status.EXPIRED):
            return gateway_payment
        gateway_payment.status = GatewayPayment.Status.EXPIRED
        gateway_payment.save(update_fields=["status", "updated_at"])
        gateway_payment.items.filter(is_active=True).update(is_active=False)
    return gateway_payment


def expire_gateway_payment(gateway_payment_id, now=None):
    """Expiry job body: expire a PENDING checkout whose window has passed.

    The provider is asked first, OUTSIDE the row lock (an HTTP call must not
    hold the lock). ProviderUnavailable propagates so the task retries.
    """
    gateway_payment = GatewayPayment.objects.get(pk=gateway_payment_id)
    if gateway_payment.status != GatewayPayment.Status.PENDING:
        return gateway_payment
    if (now or timezone.now()) < gateway_payment.expires_at:
        return gateway_payment

    if gateway_payment.provider_trx_id:
        try:
            billing = PaymentAggregator.get_billing_status(gateway_payment.provider_trx_id)
        except BillingNotFound:
            billing = None
        if billing is not None and billing.status == BillingStatus.PAID:
            # Settled by mark_gateway_payment_paid() (Step 5); never expire a paid billing.
            logger.warning(
                "Gateway payment %s is paid at the provider but still pending",
                gateway_payment.payment_no,
            )
            return gateway_payment

    return mark_gateway_payment_expired(gateway_payment.pk)


def schedule_gateway_payment_expiry(gateway_payment):
    """Queue the expiry job for after the payment window (after commit).

    Never fails the caller: without a broker (e.g. staging without Redis) or
    when publishing fails, the provider's expiry webhook still applies.
    """
    if not settings.CELERY_BROKER_URL and not settings.CELERY_TASK_ALWAYS_EAGER:
        logger.warning(
            "No Celery broker configured; expiry job for %s not queued",
            gateway_payment.payment_no,
        )
        return

    from .tasks import expire_gateway_payment_task

    payment_id = gateway_payment.pk
    eta = expiry_check_time(gateway_payment)

    def enqueue():
        try:
            expire_gateway_payment_task.apply_async(args=[payment_id], eta=eta)
        except Exception:
            logger.exception("Could not queue expiry job for gateway payment %s", payment_id)

    transaction.on_commit(enqueue)
