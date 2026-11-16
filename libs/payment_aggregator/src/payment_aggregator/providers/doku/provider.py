"""
DOKU implementation of BaseProvider: DOKU Checkout pay-in (one channel per
order) and Kirim DOKU payouts (Account Inquiry -> Transfer Bank).
"""

import datetime
import hmac
import json
import logging

from payment_aggregator.base import BaseProvider, Channel, WithdrawalRules
from payment_aggregator.exceptions import (
    InvalidCallback,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderUnavailable,
)
from payment_aggregator.providers.doku import constants, mapper, signing
from payment_aggregator.providers.doku.client import DokuClient
from payment_aggregator.providers.doku.config import DokuConfig

logger = logging.getLogger(__name__)


def _lower_headers(headers):
    return {str(key).lower(): value for key, value in (headers or {}).items()}


def _json_object(raw_body):
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise InvalidCallback("Notification body is not valid JSON")
    if not isinstance(body, dict):
        raise InvalidCallback("Notification body is not a JSON object")
    return body


class DokuProvider(BaseProvider):
    """
    ``channel_fees``: contract rate per Checkout payment method in
    constants.CHANNELS (IDR for flat channels, percent for percent channels,
    VAT included). Channels without a rate are not offered.
    ``channel_flat_fees``: IDR added to a percent channel's rate (cards).
    ``disbursement_fee``: fee per Kirim DOKU transfer, VAT included; None
    keeps withdrawals disabled. Assumed billed to the DOKU balance, so the
    bank account receives amount - fee and DOKU debits amount in total.
    """

    name = constants.PROVIDER_NAME
    # Kirim DOKU notifications are authenticated only by the static agentKey.
    confirm_transfer_callbacks = True

    def __init__(self, config=None, channel_fees=None, channel_flat_fees=None, disbursement_fee=None, session=None, now=None):
        self.config = config or DokuConfig.from_env()
        unknown = (set(channel_fees or {}) | set(channel_flat_fees or {})) - set(constants.CHANNELS)
        if unknown:
            raise ProviderNotConfigured("Unknown DOKU channel(s): " + ", ".join(sorted(unknown)))
        self.channel_fees = dict(channel_fees or {})
        self.channel_flat_fees = dict(channel_flat_fees or {})
        self.disbursement_fee = disbursement_fee
        self._now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self._private_key = None
        self.client = DokuClient(self.config, self._load_private_key, session=session)

    def _load_private_key(self):
        if self._private_key is None:
            self._private_key = signing.load_private_key(self.config.private_key.encode("utf-8"))
        return self._private_key

    # --- fee configuration ----------------------------------------------

    def get_channels(self):
        return [
            Channel(
                code=code,
                name=data["name"],
                method=data["method"],
                fee_type=data["fee_type"],
                fee=self.channel_fees.get(code),  # None -> channel not offered
                flat_fee=self.channel_flat_fees.get(code),
                min_amount=data.get("min_amount"),
                max_amount=data.get("max_amount"),
                is_active=data.get("is_active", True),
            )
            for code, data in constants.CHANNELS.items()
        ]

    def get_withdrawal_rules(self):
        if self.disbursement_fee is None:
            raise ProviderNotConfigured("DOKU disbursement_fee is not set")
        return WithdrawalRules(fee=self.disbursement_fee)

    def get_banks(self):
        return {code: name for code, (_bank_id, name) in constants.BANKS.items()}

    # --- pay-in ----------------------------------------------------------

    def create_billing(self, request):
        self.config.require_checkout_credentials()
        self.config.require_order_settings()
        payload = mapper.checkout_payload(request, self.config, self._now())
        status, body = self.client.checkout_request("POST", constants.PATH_CHECKOUT, payload)
        return mapper.checkout_result(status, body, request.reference_no)

    def get_billing_status(self, provider_trx_id):
        path = constants.PATH_ORDER_STATUS.format(invoice_number=provider_trx_id)
        status, body = self.client.checkout_request("GET", path)
        return mapper.status_result(status, body)

    def parse_billing_callback(self, raw_body, headers, request_path=""):
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        headers = _lower_headers(headers)
        # Cheap rejection of other providers' callbacks before any crypto.
        signature = headers.get("signature") or ""
        if not signature.startswith(signing.HMAC_PREFIX) or not headers.get("client-id"):
            raise InvalidCallback("Not a DOKU notification (no Client-Id / HMACSHA256 Signature)")
        self.config.require_checkout_credentials()
        if headers.get("client-id") != self.config.client_id:
            raise InvalidCallback("DOKU notification for another Client-Id")
        # DOKU signs the path of the notification URL it called.
        if not signing.verify_checkout_signature(self.config.secret_key, headers, (request_path,), raw_body):
            raise InvalidCallback("Invalid DOKU notification signature")
        return mapper.transaction_result(_json_object(raw_body))

    # --- payout ----------------------------------------------------------

    def transfer_balance(self, request):
        self.config.require_payout_credentials()
        self.config.require_transfer_settings()
        rules = self.get_withdrawal_rules()
        bank = mapper.doku_bank(request.bank_code)
        amount_sent = mapper.whole_rupiah(request.amount) - mapper.whole_rupiah(rules.fee)
        if amount_sent <= 0:
            raise ProviderRejected("Amount does not cover the DOKU transfer fee")

        # 1. Account Inquiry (mandatory; gives the sessionId). Nothing is
        #    sent yet, so an unanswered inquiry is a plain rejection.
        try:
            inquiry = self.client.snap_post(
                constants.PATH_ACCOUNT_INQUIRY, mapper.inquiry_payload(request, self.config, bank[0], amount_sent)
            )
        except ProviderUnavailable as error:
            raise ProviderRejected(
                "DOKU account inquiry did not answer; nothing was sent", provider_message=error.message, raw=error.raw
            ) from error
        mapper.raise_for_inquiry(inquiry)

        # 2. Transfer Bank. From here an unanswered request is outcome-unknown.
        body = self.client.snap_post(
            constants.PATH_TRANSFER_BANK, mapper.transfer_payload(request, self.config, bank, amount_sent, inquiry)
        )
        mapper.raise_for_transfer(body)
        return mapper.transfer_result(body, inquiry, request, bank[0], amount_sent)

    def transfer_id_for(self, request):
        """Check Status is keyed by our reference + beneficiary bank/account,
        so the id is known even when the Transfer Bank response is lost."""
        bank = constants.BANKS.get(request.bank_code)
        if bank is None or not request.reference_no or not request.account_number:
            return None
        return mapper.transfer_id(request.reference_no, bank[0], request.account_number)

    def get_transfer_status(self, provider_transfer_id):
        body = self.client.snap_post(constants.PATH_TRANSFER_STATUS, mapper.status_payload(provider_transfer_id))
        return mapper.transfer_status_result(body, provider_transfer_id)

    def parse_transfer_callback(self, raw_body, headers, request_path=""):
        """Kirim DOKU Unpaid / Refund notification. DOKU documents no
        signature algorithm for it, so the sender is authenticated by the
        agentKey header (DOKU_PAYOUT_AGENT_KEY) only; the application
        confirms it with get_transfer_status (confirm_transfer_callbacks)."""
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        headers = _lower_headers(headers)
        agent_key = headers.get("agentkey") or ""
        if not agent_key or not headers.get("requestid"):
            raise InvalidCallback("Not a Kirim DOKU notification (no agentKey / requestId)")
        self.config.require_payout_callback_credentials()
        if not hmac.compare_digest(agent_key, self.config.payout_agent_key):
            raise InvalidCallback("Invalid Kirim DOKU agentKey")
        body = _json_object(raw_body)
        if not body.get("transactionId"):
            raise InvalidCallback("Kirim DOKU notification without transactionId")
        return mapper.notify_transfer_result(body)

    def get_balance(self):
        self.config.require_balance_settings()
        body = self.client.snap_post(
            constants.PATH_BALANCE_INQUIRY, {"accountNo": self.config.payout_account_no}
        )
        return mapper.balance_result(body)

    # --- notification acknowledgement -------------------------------------

    def callback_reply(self, event, result=None):
        if event != "disbursement":
            return None  # Checkout: any 2xx
        transaction_id = ""
        if result is not None and isinstance(getattr(result, "raw", None), dict):
            transaction_id = str(result.raw.get("transactionId") or "")
        return dict(constants.NOTIFY_ACK, transactionId=transaction_id), {}
