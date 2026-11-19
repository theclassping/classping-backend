"""plan_subscriptions BillingBackend for Classping: pay through PaymentAggregator."""
from django.shortcuts import get_object_or_404

from plan_subscriptions.billing import BillingBackend

from . import payments
from .models import SubscriptionPayment


class AggregatorBilling(BillingBackend):
    def quote(self, invoice):
        return payments.channels_for(invoice.total)

    def quote_amount(self, amount):
        return payments.channels_for(amount)

    def start_payment(self, invoice, channel_code, actor, idempotency_key):
        return payments.start_payment(invoice, channel_code, actor, idempotency_key)

    def get_payment(self, payment_id, subscriber):
        payment = get_object_or_404(SubscriptionPayment.objects.select_related("invoice"), pk=payment_id, branch=subscriber)
        return payments.serialize(payments.sync(payment))

    def cancel_payment(self, payment_id, subscriber, actor):
        payment = get_object_or_404(SubscriptionPayment.objects.select_related("invoice"), pk=payment_id, branch=subscriber)
        return payments.serialize(payments.cancel(payment, actor))

    def list_payments(self, invoice):
        return [payments.serialize(p) for p in invoice.online_payments.select_related("invoice")]

    def invoice_voided(self, invoice):
        for payment in invoice.online_payments.filter(status=SubscriptionPayment.Status.PENDING):
            payments._close_id(payment.pk, SubscriptionPayment.Status.CANCELLED)
