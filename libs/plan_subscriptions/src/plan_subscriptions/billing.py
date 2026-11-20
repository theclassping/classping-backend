"""
How invoices are paid. The host implements BillingBackend and points
PLAN_SUBSCRIPTIONS["BILLING_BACKEND"] at it. When the host learns a payment
succeeded (webhook), it calls services.mark_invoice_paid(invoice, ref).

All methods return plain dicts so the API can serialize them as they are.
"""
from .exceptions import BillingNotSupported


class BillingBackend:
    def quote(self, invoice):
        """Payment channels for this invoice, each with its fee and amount to pay.

        [{"channel_code", "name", "payment_method", "fee", "amount"}]
        """
        raise NotImplementedError

    def start_payment(self, invoice, channel_code, actor, idempotency_key):
        """Create a payment; returns {"id", "status", "amount", "payment_code", "payment_url", "expires_at", ...}."""
        raise NotImplementedError

    def get_payment(self, payment_id, subscriber):
        raise NotImplementedError

    def cancel_payment(self, payment_id, subscriber, actor):
        raise NotImplementedError

    def quote_amount(self, amount):
        """Channels and fees for paying ``amount`` before an invoice exists (add-on quote)."""
        return []

    def list_payments(self, invoice):
        return []

    def invoice_voided(self, invoice):
        """The invoice was voided: stop any pending payment for it (optional)."""


class ManualBilling(BillingBackend):
    """No online payment: an admin marks invoices paid after a bank transfer."""

    def quote(self, invoice):
        return []

    def start_payment(self, invoice, channel_code, actor, idempotency_key):
        raise BillingNotSupported()

    def get_payment(self, payment_id, subscriber):
        raise BillingNotSupported()

    def cancel_payment(self, payment_id, subscriber, actor):
        raise BillingNotSupported()
