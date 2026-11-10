"""
Rintisan implementation of BaseProvider.
"""

import hmac
import json
import logging

from apps.payment_aggregator.base import (
    BaseProvider,
    Channel,
    WithdrawalRules,
)
from apps.payment_aggregator.exceptions import InvalidCallback
from apps.payment_aggregator.providers.rintisan import constants, mapper, signing
from apps.payment_aggregator.providers.rintisan.client import RintisanClient
from apps.payment_aggregator.providers.rintisan.config import RintisanConfig

logger = logging.getLogger(__name__)

PATH_CREATE = "/create"
PATH_QUERY_PAYMENT = "/querypayment"
PATH_BALANCE = "/balance"
PATH_MAKE_DISBURSEMENT = "/makedisbursement"
PATH_STATUS_DISBURSEMENT = "/statusdisbursement"


def _lower_headers(headers):
    return {str(key).lower(): value for key, value in (headers or {}).items()}


class RintisanProvider(BaseProvider):
    name = constants.PROVIDER_NAME

    def __init__(self, config=None, session=None):
        self.config = config or RintisanConfig.from_env()
        self._private_key = None
        self._public_key = None
        self.client = RintisanClient(self.config, self._load_private_key, session=session)

    # --- keys ------------------------------------------------------------

    def _load_private_key(self):
        # Credentials are checked by RintisanClient.post before signing.
        if self._private_key is None:
            self._private_key = signing.load_private_key(
                self.config.private_key.encode("utf-8")
            )
        return self._private_key

    def _load_public_key(self):
        if self._public_key is None:
            self.config.require_callback_credentials()
            self._public_key = signing.load_public_key(
                self.config.public_key.encode("utf-8")
            )
        return self._public_key

    # --- fee configuration ----------------------------------------------

    def get_channels(self):
        return [
            Channel(
                code=code,
                name=data["name"],
                method=data["method"],
                fee_type=data["fee_type"],
                fee=data["fee"],
                min_amount=data.get("min_amount"),
                max_amount=data.get("max_amount"),
                is_active=data.get("is_active", True),
            )
            for code, data in constants.CHANNELS.items()
        ]

    def get_withdrawal_rules(self):
        return WithdrawalRules(fee=constants.DISBURSEMENT_FEE)

    def get_banks(self):
        return dict(constants.BANK_CODES)

    # --- pay-in ----------------------------------------------------------

    def create_billing(self, request):
        body = self.client.post(
            PATH_CREATE, mapper.billing_payload(request, self.config.payer_email)
        )
        mapper.raise_for_billing_response(body)
        return mapper.billing_result(body, reference_no=request.reference_no)

    def get_billing_status(self, provider_trx_id):
        body = self.client.post(PATH_QUERY_PAYMENT, {"trx_id": provider_trx_id})
        mapper.raise_for_billing_response(body)
        return mapper.billing_result(body)

    def parse_billing_callback(self, raw_body, headers):
        body = self._verify_callback(raw_body, headers, signature_required=True)
        return mapper.billing_result(body)

    # --- payout ----------------------------------------------------------

    def transfer_balance(self, request):
        body = self.client.post(PATH_MAKE_DISBURSEMENT, mapper.transfer_payload(request))
        mapper.raise_for_transfer_response(body)
        return mapper.transfer_result(body, reference_no=request.reference_no)

    def get_transfer_status(self, provider_transfer_id):
        body = self.client.post(
            PATH_STATUS_DISBURSEMENT, {"disbursement_id": provider_transfer_id}
        )
        mapper.raise_for_transfer_status_response(body)
        return mapper.transfer_result(body)

    def parse_transfer_callback(self, raw_body, headers):
        body = self._verify_callback(
            raw_body,
            headers,
            signature_required=self.config.require_transfer_callback_signature,
        )
        return mapper.transfer_result(body)

    def get_balance(self):
        body = self.client.get(PATH_BALANCE)
        mapper.raise_for_balance_response(body)
        return mapper.provider_balance(body)

    # --- callbacks -------------------------------------------------------

    def _verify_callback(self, raw_body, headers, signature_required):
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        headers = _lower_headers(headers)

        expected_token = self.config.callback_token
        if expected_token:
            received_token = headers.get("x-callback-token") or ""
            if not hmac.compare_digest(str(received_token), expected_token):
                raise InvalidCallback("Invalid callback token")

        signature = headers.get("x-signature") or ""
        if signature or signature_required:
            if not signing.verify(
                self.config.client_id, raw_body, signature, self._load_public_key()
            ):
                raise InvalidCallback("Invalid callback signature")

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise InvalidCallback("Callback body is not valid JSON")
        if not isinstance(body, dict):
            raise InvalidCallback("Callback body is not a JSON object")
        return body
