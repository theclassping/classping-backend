"""
PaymentAggregator: the single entry point business code uses.

    from decimal import Decimal
    from payment_aggregator import PaymentAggregator
    from payment_aggregator.providers.rintisan import RintisanConfig, RintisanProvider

    provider = RintisanProvider(
        RintisanConfig.from_env(),
        channel_fees={"VABCA": Decimal("5000"), "CC": Decimal("2")},
        disbursement_fee=Decimal("2500"),
    )
    aggregator = PaymentAggregator(provider)

    aggregator.get_channels(invoice_total)
    aggregator.calculate_transaction_fee("VABCA", invoice_total)
    aggregator.create_billing(BillingRequest(...))
    aggregator.calculate_withdrawal(amount)
    aggregator.transfer_balance(TransferRequest(...))

The library keeps no global state: the application decides which provider to
build, with which rates, and where to keep the aggregator.
"""

from payment_aggregator import fees
from payment_aggregator.exceptions import ChannelNotAvailable


class PaymentAggregator:
    def __init__(self, provider):
        self.provider = provider

    # --- configuration ---------------------------------------------------

    def provider_name(self):
        """Name of the active provider (store it with each payment)."""
        return self.provider.name

    def get_banks(self):
        return self.provider.get_banks()

    def is_supported_bank(self, bank_code):
        return bank_code in self.provider.get_banks()

    def get_withdrawal_rules(self):
        return self.provider.get_withdrawal_rules()

    # --- fees ------------------------------------------------------------

    def get_channel(self, channel_code):
        for channel in self.provider.get_channels():
            if channel.code == channel_code:
                return channel
        raise ChannelNotAvailable("Unknown channel {}".format(channel_code))

    def get_channels(self, invoice_total):
        """Usable channels for ``invoice_total`` with fee and total per channel."""
        return fees.available_channels(self.provider.get_channels(), invoice_total)

    def calculate_transaction_fee(self, channel_code, invoice_total):
        return fees.calculate_transaction_fee(self.get_channel(channel_code), invoice_total)

    def calculate_withdrawal(self, amount):
        return fees.calculate_withdrawal(self.provider.get_withdrawal_rules(), amount)

    # --- pay-in ----------------------------------------------------------

    def create_billing(self, request):
        return self.provider.create_billing(request)

    def get_billing_status(self, provider_trx_id):
        return self.provider.get_billing_status(provider_trx_id)

    def parse_billing_callback(self, raw_body, headers, request_path=""):
        return self.provider.parse_billing_callback(raw_body, headers, request_path=request_path)

    def callback_reply(self, event):
        """(body, headers) the provider requires in reply to a notification, or None."""
        return self.provider.callback_reply(event)

    # --- payout ----------------------------------------------------------

    def transfer_balance(self, request):
        return self.provider.transfer_balance(request)

    def get_transfer_status(self, provider_transfer_id):
        return self.provider.get_transfer_status(provider_transfer_id)

    def parse_transfer_callback(self, raw_body, headers, request_path=""):
        return self.provider.parse_transfer_callback(raw_body, headers, request_path=request_path)

    def get_balance(self):
        return self.provider.get_balance()
