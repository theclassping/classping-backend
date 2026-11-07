"""
PaymentAggregator: the single entry point business code uses.

    from apps.payment_aggregator.aggregator import PaymentAggregator

    PaymentAggregator.get_channels(invoice_total)
    PaymentAggregator.calculate_transaction_fee("VABCA", invoice_total)
    PaymentAggregator.create_billing(BillingRequest(...))
    PaymentAggregator.calculate_withdrawal(amount)
    PaymentAggregator.transfer_balance(TransferRequest(...))

The concrete provider is chosen by constants.PAYMENT_AGGREGATOR_PROVIDER.
"""

import threading

from django.utils.module_loading import import_string

from apps.payment_aggregator import constants, fees
from apps.payment_aggregator.exceptions import (
    ChannelNotAvailable,
    ProviderNotConfigured,
)

_lock = threading.Lock()
_provider = None


def get_provider():
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                key = constants.PAYMENT_AGGREGATOR_PROVIDER
                path = constants.PROVIDER_CLASSES.get(key)
                if not path:
                    raise ProviderNotConfigured("Unknown payment aggregator provider: {}".format(key))
                _provider = import_string(path)()
    return _provider


def set_provider(provider):
    """Override the active provider (tests). Pass None to reset."""
    global _provider
    with _lock:
        _provider = provider


class PaymentAggregator:
    # --- configuration ---------------------------------------------------

    @classmethod
    def provider_name(cls):
        return get_provider().name

    @classmethod
    def get_banks(cls):
        return get_provider().get_banks()

    @classmethod
    def is_supported_bank(cls, bank_code):
        return bank_code in get_provider().get_banks()

    @classmethod
    def get_payment_deadline_days(cls):
        return get_provider().get_payment_deadline_days()

    @classmethod
    def get_withdrawal_rules(cls):
        return get_provider().get_withdrawal_rules()

    # --- fees ------------------------------------------------------------

    @classmethod
    def get_channel(cls, channel_code):
        for channel in get_provider().get_channels():
            if channel.code == channel_code:
                return channel
        raise ChannelNotAvailable("Unknown channel {}".format(channel_code))

    @classmethod
    def get_channels(cls, invoice_total):
        """Usable channels for ``invoice_total`` with fee and total per channel."""
        return fees.available_channels(get_provider().get_channels(), invoice_total)

    @classmethod
    def calculate_transaction_fee(cls, channel_code, invoice_total):
        return fees.calculate_transaction_fee(cls.get_channel(channel_code), invoice_total)

    @classmethod
    def calculate_withdrawal(cls, amount):
        return fees.calculate_withdrawal(get_provider().get_withdrawal_rules(), amount)

    # --- pay-in ----------------------------------------------------------

    @classmethod
    def create_billing(cls, request):
        return get_provider().create_billing(request)

    @classmethod
    def get_billing_status(cls, provider_trx_id):
        return get_provider().get_billing_status(provider_trx_id)

    @classmethod
    def parse_billing_callback(cls, raw_body, headers):
        return get_provider().parse_billing_callback(raw_body, headers)

    # --- payout ----------------------------------------------------------

    @classmethod
    def transfer_balance(cls, request):
        return get_provider().transfer_balance(request)

    @classmethod
    def get_transfer_status(cls, provider_transfer_id):
        return get_provider().get_transfer_status(provider_transfer_id)

    @classmethod
    def parse_transfer_callback(cls, raw_body, headers):
        return get_provider().parse_transfer_callback(raw_body, headers)

    @classmethod
    def get_balance(cls):
        return get_provider().get_balance()
