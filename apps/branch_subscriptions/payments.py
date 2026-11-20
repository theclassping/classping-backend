"""
Online payment of subscription invoices through the payment aggregator (DANA).

The branch pays the provider fee on top (gross-up), the same formula as
parents (PaymentAggregator.calculate_transaction_fee). payment_no starts with
"SUB-": the shared payment webhook hands those callbacks to apply_callback().
The money is Classping's: nothing here touches the branch wallet.
"""
import datetime
import logging
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import ProviderUnavailable
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.payment_aggregator import PaymentAggregator
from payment_aggregator import exceptions as provider_errors
from payment_aggregator.base import BillingRequest, BillingStatus
from plan_subscriptions import services
from plan_subscriptions.exceptions import InvalidRequest, InvoiceNotPayable
from plan_subscriptions.models import SubscriptionInvoice

from .models import SubscriptionPayment

logger = logging.getLogger(__name__)

PREFIX = "SUB-"
# Same window as parent checkouts: the VA must be paid within an hour.
PAYMENT_WINDOW_MINUTES = 60

P = SubscriptionPayment.Status


def owns_reference(reference_no):
    return bool(reference_no) and str(reference_no).startswith(PREFIX)


def find_by_reference(reference_no, provider_trx_id=None):
    payment = SubscriptionPayment.objects.filter(payment_no=reference_no).first() if reference_no else None
    if payment is None and provider_trx_id:
        payment = SubscriptionPayment.objects.filter(provider_trx_id=provider_trx_id).first()
    return payment


def channels_for(amount):
    """[{code, name, payment_method, transaction_fee, amount}] for paying ``amount``."""
    return [
        {
            "code": fee.channel_code,
            "name": fee.channel_name,
            "payment_method": fee.payment_method,
            "transaction_fee": str(fee.transaction_fee),
            "amount": str(fee.amount),
        }
        for fee in PaymentAggregator.get_channels(amount)
    ]


def serialize(payment):
    return {
        "id": payment.pk,
        "payment_no": payment.payment_no,
        "invoice_id": payment.invoice_id,
        "invoice_number": payment.invoice.number,
        "status": payment.status,
        "channel_code": payment.channel_code,
        "channel_name": payment.channel_name,
        "payment_method": payment.payment_method,
        "invoice_total": str(payment.invoice_total),
        "transaction_fee": str(payment.transaction_fee),
        "amount": str(payment.amount),
        "payment_code": payment.payment_code,
        "payment_link": payment.payment_link,
        "billing_url": payment.billing_url,
        "expires_at": payment.expires_at,
        "paid_at": payment.paid_at,
        "created_at": payment.created_at,
    }


def _payer(actor, branch):
    staff = getattr(actor, "staff", None)
    name = ""
    phone = ""
    if staff is not None:
        name = f"{staff.first_name} {staff.last_name}".strip()
        phone = staff.phone
    phone = phone or branch.phone
    name = name or branch.name
    try:
        return name, normalize_phone(phone)
    except InvalidPhoneNumber:
        raise InvalidRequest("A valid phone number is needed on your staff profile or the branch to pay online.")


def start_payment(invoice, channel_code, actor, idempotency_key=""):
    invoice = SubscriptionInvoice.objects.select_related("subscription__subscriber").get(pk=invoice.pk)
    branch = invoice.subscription.subscriber
    if idempotency_key:
        earlier = SubscriptionPayment.objects.filter(branch=branch, idempotency_key=idempotency_key).first()
        if earlier is not None:
            return serialize(earlier)
    if invoice.status != SubscriptionInvoice.Status.OPEN:
        raise InvoiceNotPayable()
    try:
        fee = PaymentAggregator.calculate_transaction_fee(channel_code, invoice.total)
    except provider_errors.ChannelNotAvailable:
        raise InvalidRequest(f"Channel {channel_code} is not available for this amount.")
    payer_name, payer_phone = _payer(actor, branch)
    now = timezone.now()
    expires_at = now + datetime.timedelta(minutes=PAYMENT_WINDOW_MINUTES)
    try:
        with transaction.atomic():
            # One pending checkout per invoice: a new one replaces the old.
            for pending in SubscriptionPayment.objects.select_for_update().filter(invoice=invoice, status=P.PENDING):
                _close(pending, P.CANCELLED)
            payment = SubscriptionPayment.objects.create(
                payment_no="TMP-" + uuid.uuid4().hex,
                invoice=invoice, branch=branch, staff=getattr(actor, "staff", None),
                provider=PaymentAggregator.provider_name(), channel_code=fee.channel_code,
                channel_name=fee.channel_name, payment_method=fee.payment_method,
                invoice_total=fee.invoice_total, transaction_fee=fee.transaction_fee, amount=fee.amount,
                idempotency_key=idempotency_key or "", expires_at=expires_at,
            )
            payment.payment_no = "{}{:%Y%m%d}-{:06d}".format(PREFIX, timezone.localdate(), payment.pk)
            payment.save(update_fields=["payment_no"])
    except IntegrityError:
        earlier = SubscriptionPayment.objects.filter(branch=branch, idempotency_key=idempotency_key).first()
        if earlier is None:
            raise
        return serialize(earlier)

    request = BillingRequest(
        reference_no=payment.payment_no,
        channel_code=payment.channel_code,
        amount=payment.amount,
        invoice_date=timezone.localdate(),
        expires_at=expires_at,
        payer_name=payer_name,
        payer_phone=payer_phone,
        identifier=payment.payment_no,
        note=invoice.number,
    )
    aggregator = PaymentAggregator.using(payment.provider)
    try:
        try:
            billing = aggregator.create_billing(request)
        except provider_errors.DuplicateBilling as error:
            billing = aggregator.get_billing_status(error.provider_trx_id)
    except provider_errors.PaymentAggregatorError:
        logger.exception("Subscription billing %s could not be created", payment.payment_no)
        _close_id(payment.pk, P.FAILED)
        raise ProviderUnavailable(subscription_payment_id=payment.pk)

    SubscriptionPayment.objects.filter(pk=payment.pk).update(
        provider_trx_id=billing.provider_trx_id or None,
        payment_code=billing.payment_code,
        payment_link=billing.payment_link,
        billing_url=billing.billing_url,
        provider_response=billing.raw,
        updated_at=timezone.now(),
    )
    payment.refresh_from_db()
    return serialize(payment)


def _close(payment, status):
    if payment.can_transition_to(status):
        payment.status = status
        payment.save(update_fields=["status", "updated_at"])
    return payment


def _close_id(payment_id, status):
    with transaction.atomic():
        payment = SubscriptionPayment.objects.select_for_update().get(pk=payment_id)
        return _close(payment, status)


def mark_paid(payment_id, paid_at=None):
    """Provider confirmed payment: pay the invoice (activates the plan / add-on)."""
    with transaction.atomic():
        payment = SubscriptionPayment.objects.select_for_update().select_related("invoice").get(pk=payment_id)
        if payment.status == P.PAID:
            return payment
        payment.status = P.PAID
        payment.paid_at = paid_at or timezone.now()
        payment.save(update_fields=["status", "paid_at", "updated_at"])
        services.mark_invoice_paid(
            payment.invoice, paid_ref=payment.payment_no, paid_at=payment.paid_at,
            payment={"payment_method": payment.channel_name or payment.payment_method, "amount": payment.amount},
        )
    return payment


def apply_billing_result(payment, billing):
    if billing.status == BillingStatus.PAID:
        if billing.amount is not None and billing.amount != payment.amount:
            logger.error(
                "Subscription payment %s: provider amount %s != %s; not applied",
                payment.payment_no, billing.amount, payment.amount,
            )
            return payment
        return mark_paid(payment.pk, billing.paid_at)
    return payment


def apply_callback(provider, billing):
    """Called by payment_gateway.services for "SUB-" references. Returns 'ok' / 'ignored'."""
    payment = find_by_reference(billing.reference_no, billing.provider_trx_id)
    if payment is None:
        logger.error("Subscription callback for unknown payment %s / %s", billing.reference_no, billing.provider_trx_id)
        return "ignored"
    if payment.provider and payment.provider != provider:
        logger.error("Subscription callback from %s for %s created with %s", provider, payment.payment_no, payment.provider)
        return "ignored"
    SubscriptionPayment.objects.filter(pk=payment.pk).update(
        callback_payload=billing.raw, callback_received_at=timezone.now(),
    )
    if not payment.provider_trx_id and billing.provider_trx_id:
        SubscriptionPayment.objects.filter(pk=payment.pk, provider_trx_id__isnull=True).update(
            provider_trx_id=billing.provider_trx_id,
        )
    apply_billing_result(payment, billing)
    return "ok"


def sync(payment):
    """Ask the provider; pending past its window and unpaid -> expired."""
    if payment.status == P.PENDING and payment.provider_trx_id:
        try:
            billing = PaymentAggregator.using(payment.provider).get_billing_status(payment.provider_trx_id)
        except provider_errors.PaymentAggregatorError:
            logger.warning("Could not sync subscription payment %s", payment.payment_no)
        else:
            payment = apply_billing_result(payment, billing)
    if payment.status == P.PENDING and timezone.now() >= payment.expires_at:
        payment = _close_id(payment.pk, P.EXPIRED)
    return payment


def expire_overdue():
    """Hourly: close checkouts whose window passed (after asking the provider)."""
    count = 0
    for payment in SubscriptionPayment.objects.filter(status=P.PENDING, expires_at__lte=timezone.now()):
        if sync(payment).status != P.PENDING:
            count += 1
    return count


def cancel(payment, actor=None):
    with transaction.atomic():
        payment = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != P.PENDING:
            raise InvalidRequest("Only a pending payment can be cancelled.")
        _close(payment, P.CANCELLED)
    return payment
