"""
DANA implementation of BaseProvider: Gapura Custom Checkout pay-in.

Payouts (Transfer to Bank) and the provider balance are not implemented yet:
they raise ProviderNotConfigured, so withdrawals through DANA stay disabled.
"""

import json
import logging

from payment_aggregator.base import BaseProvider, Channel, WithdrawalRules
from payment_aggregator.exceptions import InvalidCallback, ProviderNotConfigured
from payment_aggregator.providers.dana import constants, mapper, signing
from payment_aggregator.providers.dana.client import DanaClient
from payment_aggregator.providers.dana.config import DanaConfig

logger = logging.getLogger(__name__)


def _lower_headers(headers):
    return {str(key).lower(): value for key, value in (headers or {}).items()}


class DanaProvider(BaseProvider):
    """
    ``channel_fees``: contract rate per payOption in constants.CHANNELS (IDR for
    flat channels, percent for percent channels, VAT included). Channels
    without a rate are not offered.
    ``disbursement_fee``: not used until Transfer to Bank is implemented.
    """

    name = constants.PROVIDER_NAME

    def __init__(self, config=None, channel_fees=None, disbursement_fee=None, session=None):
        self.config = config or DanaConfig.from_env()
        unknown = set(channel_fees or {}) - set(constants.CHANNELS)
        if unknown:
            raise ProviderNotConfigured("Unknown DANA channel(s): " + ", ".join(sorted(unknown)))
        self.channel_fees = dict(channel_fees or {})
        self.disbursement_fee = disbursement_fee
        self._private_key = None
        self._public_key = None
        self.client = DanaClient(self.config, self._load_private_key, session=session)

    # --- keys ------------------------------------------------------------

    def _load_private_key(self):
        if self._private_key is None:
            self._private_key = signing.load_private_key(self.config.private_key.encode("utf-8"))
        return self._private_key

    def _load_public_key(self):
        if self._public_key is None:
            self.config.require_callback_credentials()
            self._public_key = signing.load_public_key(self.config.public_key.encode("utf-8"))
        return self._public_key

    # --- fee configuration ----------------------------------------------

    def get_channels(self):
        return [
            Channel(
                code=code,
                name=data["name"],
                method=data["method"],
                fee_type=data["fee_type"],
                fee=self.channel_fees.get(code),  # None -> channel not offered
                min_amount=data.get("min_amount"),
                max_amount=data.get("max_amount"),
                is_active=data.get("is_active", True),
            )
            for code, data in constants.CHANNELS.items()
        ]

    def get_withdrawal_rules(self):
        if self.disbursement_fee is None:
            raise ProviderNotConfigured("DANA disbursement_fee is not set")
        return WithdrawalRules(fee=self.disbursement_fee)

    def get_banks(self):
        # Transfer to Bank is not implemented yet: no payout bank is offered.
        return {}

    # --- pay-in ----------------------------------------------------------

    def order_request(self, request):
        """(url, headers, body) of the signed Create Order, without sending it."""
        self.config.require_order_settings()
        return self.client.signed_request(
            constants.PATH_CREATE_ORDER, mapper.order_payload(request, self.config)
        )

    def create_billing(self, request):
        self.config.require_order_settings()
        body = self.client.post(constants.PATH_CREATE_ORDER, mapper.order_payload(request, self.config))
        mapper.raise_for_order_response(body)
        return mapper.order_result(body, request.reference_no)

    def get_billing_status(self, provider_trx_id):
        body = self.client.post(constants.PATH_QUERY_PAYMENT, mapper.query_payload(provider_trx_id, self.config))
        mapper.raise_for_query_response(body)
        return mapper.query_result(body)

    def parse_billing_callback(self, raw_body, headers, request_path=""):
        body = self._verify_callback(raw_body, headers, request_path, constants.SNAP_PATH_FINISH_NOTIFY)
        return mapper.notify_result(body)

    def callback_reply(self, event):
        ack = constants.ACK_TRANSFER_NOTIFY if event == "disbursement" else constants.ACK_FINISH_NOTIFY
        return dict(ack), {"X-TIMESTAMP": signing.timestamp()}

    # --- payout (not implemented yet) -------------------------------------

    def _payout_not_ready(self):
        raise ProviderNotConfigured("DANA Transfer to Bank is not implemented yet")

    def transfer_balance(self, request):
        self._payout_not_ready()

    def get_transfer_status(self, provider_transfer_id):
        self._payout_not_ready()

    def parse_transfer_callback(self, raw_body, headers, request_path=""):
        self._payout_not_ready()

    def get_balance(self):
        self._payout_not_ready()

    # --- callbacks -------------------------------------------------------

    def _verify_callback(self, raw_body, headers, request_path, snap_path):
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        headers = _lower_headers(headers)
        # Cheap rejection of other providers' callbacks before any crypto.
        if not headers.get("x-signature") or not headers.get("x-timestamp"):
            raise InvalidCallback("Not a DANA notification (no X-SIGNATURE / X-TIMESTAMP)")
        if not signing.verify(
            "POST",
            (request_path, snap_path),
            raw_body,
            headers.get("x-timestamp"),
            headers.get("x-signature"),
            self._load_public_key(),
        ):
            raise InvalidCallback("Invalid DANA notification signature")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise InvalidCallback("Notification body is not valid JSON")
        if not isinstance(body, dict):
            raise InvalidCallback("Notification body is not a JSON object")
        return body
