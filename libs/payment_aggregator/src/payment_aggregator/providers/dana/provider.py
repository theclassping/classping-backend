"""
DANA implementation of BaseProvider: Gapura Custom Checkout pay-in, cancel,
refund, and Disbursement to Bank payouts.

Payouts are paid from the Merchant Disbursement Account (MDA), which is only
funded by top-up (VA in the Merchant Portal), not by Gapura settlement.
The provider balance (Check Disbursement Account, a DANA Open API) is not
implemented yet: get_balance raises ProviderNotConfigured.
"""

import json
import logging

from payment_aggregator.banks import BANKS
from payment_aggregator.base import BaseProvider, Channel, WithdrawalRules
from payment_aggregator.exceptions import (
    InvalidCallback,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderUnavailable,
)
from payment_aggregator.providers.dana import constants, mapper, settlement, signing
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
    ``disbursement_fee``: fee per Transfer to Bank kept from the withdrawn
    amount (the bank account receives amount - fee); DANA's own transfer
    charge is billed to the MDA (chargeTarget MERCHANT). None keeps
    withdrawals disabled.
    """

    # Transfer notifications only prompt a status inquiry (their body is not
    # documented); the status inquiry decides.
    confirm_transfer_callbacks = True

    # Query Payment has no settlement field: only DANA's daily settlement
    # file says a payment was settled.
    settlement_via_file = True

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
            try:
                self._private_key = signing.load_private_key(self.config.private_key.encode("utf-8"))
            except ValueError as exc:
                raise ProviderNotConfigured("Invalid {}: {}".format(self.config.private_key_env, exc)) from exc
        return self._private_key

    def _load_public_key(self):
        if self._public_key is None:
            self.config.require_callback_credentials()
            try:
                self._public_key = signing.load_public_key(self.config.public_key.encode("utf-8"))
            except ValueError as exc:
                raise ProviderNotConfigured("Invalid DANA_PUBLIC_KEY: {}".format(exc)) from exc
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
        # Withdrawals stay off until the payout settings are present.
        self.config.require_payout_settings()
        return WithdrawalRules(fee=self.disbursement_fee)

    def get_banks(self):
        return {code: name for code, (_bi_code, name) in BANKS.items()}

    def parse_settlement_file(self, content):
        return settlement.parse(content)

    # --- pay-in ----------------------------------------------------------

    def consult_pay(self, amount):
        """Return DANA's available payment options for the given IDR amount."""
        self.config.require_request_credentials()
        payload = mapper.consult_pay_payload(amount, self.config)
        body = self.client.post(
            constants.PATH_CONSULT_PAY, payload, timeout=constants.CONSULT_PAY_TIMEOUT_SECONDS
        )
        mapper.raise_for_consult_pay_response(body)
        return body.get("paymentInfos") or []

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

    # --- cancel / refund -------------------------------------------------

    supports_cancel_billing = True
    supports_refund = True

    def cancel_billing(self, reference_no, provider_trx_id="", reason=""):
        self.config.require_order_settings()
        body = self.client.post(
            constants.PATH_CANCEL_ORDER, mapper.cancel_payload(reference_no, provider_trx_id, reason, self.config)
        )
        mapper.raise_for_cancel_response(body)
        return mapper.cancel_result(body, reference_no)

    def refund_billing(self, request):
        self.config.require_order_settings()
        body = self.client.post(constants.PATH_REFUND_ORDER, mapper.refund_payload(request, self.config))
        mapper.raise_for_refund_response(body)
        return mapper.refund_result(body, request)

    def callback_reply(self, event, result=None):
        ack = constants.ACK_TRANSFER_NOTIFY if event == "disbursement" else constants.ACK_FINISH_NOTIFY
        return dict(ack), {"X-TIMESTAMP": signing.timestamp()}

    # --- payout: Disbursement to Bank -------------------------------------

    def transfer_balance(self, request):
        rules = self.get_withdrawal_rules()  # fee + payout settings
        bank_code = mapper.dana_bank(request.bank_code)
        amount_sent = mapper.whole_rupiah(request.amount) - mapper.whole_rupiah(rules.fee)
        if amount_sent <= 0:
            raise ProviderRejected("Amount does not cover the transfer fee")

        # 1. Bank account inquiry: validates the account before any money
        #    moves. Nothing is sent yet, so no answer is a plain rejection.
        try:
            inquiry = self.client.post(
                constants.PATH_BANK_ACCOUNT_INQUIRY,
                mapper.bank_inquiry_payload(request, self.config, bank_code, amount_sent),
            )
        except ProviderUnavailable as error:
            raise ProviderRejected(
                "DANA account inquiry did not answer; nothing was sent", provider_message=error.message, raw=error.raw
            ) from error
        mapper.raise_for_bank_inquiry(inquiry)

        # 2. Transfer to Bank. From here no answer means outcome unknown; a
        #    retry must reuse partnerReferenceNo (our reference_no).
        body = self.client.post(
            constants.PATH_TRANSFER_BANK, mapper.transfer_payload(request, self.config, bank_code, amount_sent)
        )
        mapper.raise_for_transfer(body)
        return mapper.transfer_result(body, inquiry, request, amount_sent)

    def transfer_id_for(self, request):
        """The status inquiry is keyed by our partnerReferenceNo, so the id is
        known even when the Transfer to Bank response was lost."""
        return request.reference_no or None

    def get_transfer_status(self, provider_transfer_id):
        body = self.client.post(constants.PATH_TRANSFER_STATUS, mapper.transfer_status_payload(provider_transfer_id))
        return mapper.transfer_status_result(body, provider_transfer_id)

    def parse_transfer_callback(self, raw_body, headers, request_path=""):
        body = self._verify_callback(raw_body, headers, request_path, constants.SNAP_PATH_TRANSFER_NOTIFY)
        return mapper.notify_transfer_result(body)

    def get_balance(self):
        # Check Disbursement Account is a DANA Open API (other envelope and
        # signature than SNAP); not implemented yet.
        raise ProviderNotConfigured("DANA disbursement balance check is not implemented yet")

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
            # TEMPORARY (sandbox debugging): everything needed to replay the
            # verification offline. Remove once notifications verify.
            logger.warning(
                "DANA signature mismatch: paths=%r x-timestamp=%r x-signature=%r body=%r",
                (request_path, snap_path),
                headers.get("x-timestamp"),
                headers.get("x-signature"),
                raw_body[:4000].decode("utf-8", "replace"),
            )
            raise InvalidCallback("Invalid DANA notification signature")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise InvalidCallback("Notification body is not valid JSON")
        if not isinstance(body, dict):
            raise InvalidCallback("Notification body is not a JSON object")
        return body
