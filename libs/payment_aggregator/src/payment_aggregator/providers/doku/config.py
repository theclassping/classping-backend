"""
DOKU credentials. Build DokuConfig(...) directly, or read them from the
environment with DokuConfig.from_env() (never hardcode them):

DOKU_ENV                 sandbox | production (default: sandbox)
DOKU_BASE_URL            optional override of the base URL
DOKU_CLIENT_ID           Client-Id (Back Office > Integration > API Keys)
DOKU_SECRET_KEY          Secret Key: signs Checkout requests and verifies
                         payment notifications (HMAC-SHA256)
DOKU_NOTIFY_URL          our payment notification URL, sent with every order
                         (additional_info.override_notification_url)
DOKU_RETURN_URL          page the payer returns to after paying (callback_url)

Kirim DOKU (payout). Client id / secret default to the Checkout ones:
DOKU_PAYOUT_CLIENT_ID    X-PARTNER-ID / X-CLIENT-KEY
DOKU_PAYOUT_SECRET_KEY   clientSecret of the HMAC-SHA512 signature
DOKU_PRIVATE_KEY         our RSA private key (PEM, or literal \\n escapes);
                         its public key is uploaded to the DOKU dashboard
                         (variable name configurable: from_env(private_key_env=...))
DOKU_PAYOUT_CHANNEL_ID   CHANNEL-ID header (default H2H)
DOKU_PAYOUT_CHANNEL_CODE additionalInfo.channelCode: 07 bank deposit, 11 BI-FAST,
                         empty = not sent (DOKU's default route)
DOKU_PAYOUT_ACCOUNT_NO   accountNo of the Balance Inquiry
DOKU_PAYOUT_AGENT_KEY    agentKey header DOKU sends with payout notifications
DOKU_SENDER_PHONE        customerNumber (62...), also the beneficiary phone
                         when the withdrawal has none
DOKU_SENDER_FIRST_NAME / DOKU_SENDER_LAST_NAME
DOKU_SENDER_ID_NUMBER / DOKU_SENDER_ID_TYPE (KTP | PASSPORT, default KTP)
                         sender identity required by Transfer Bank
"""

import os
from dataclasses import dataclass

from payment_aggregator.exceptions import ProviderNotConfigured
from payment_aggregator.providers.doku import constants
from payment_aggregator.utils import env_pem


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class DokuConfig:
    base_url: str
    client_id: str
    secret_key: str
    notify_url: str = ""
    return_url: str = ""
    payout_client_id: str = ""
    payout_secret_key: str = ""
    private_key: str = ""
    payout_channel_id: str = constants.DEFAULT_CHANNEL_ID
    payout_channel_code: str = ""
    payout_account_no: str = ""
    payout_agent_key: str = ""
    sender_phone: str = ""
    sender_first_name: str = ""
    sender_last_name: str = ""
    sender_id_number: str = ""
    sender_id_type: str = constants.DEFAULT_SENDER_ID_TYPE
    timeout: int = constants.REQUEST_TIMEOUT_SECONDS
    # Only used to name the missing setting in ProviderNotConfigured.
    private_key_env: str = "DOKU_PRIVATE_KEY"

    @classmethod
    def from_env(cls, private_key_env="DOKU_PRIVATE_KEY", default_notify_url="", default_return_url=""):
        env = _env("DOKU_ENV", "sandbox").lower()
        default_url = constants.BASE_URL_PRODUCTION if env == "production" else constants.BASE_URL_SANDBOX
        client_id = _env("DOKU_CLIENT_ID")
        secret_key = _env("DOKU_SECRET_KEY")
        return cls(
            base_url=_env("DOKU_BASE_URL", default_url).rstrip("/"),
            client_id=client_id,
            secret_key=secret_key,
            notify_url=_env("DOKU_NOTIFY_URL", default_notify_url),
            return_url=_env("DOKU_RETURN_URL", default_return_url),
            payout_client_id=_env("DOKU_PAYOUT_CLIENT_ID", client_id),
            payout_secret_key=_env("DOKU_PAYOUT_SECRET_KEY", secret_key),
            private_key=env_pem(private_key_env),
            payout_channel_id=_env("DOKU_PAYOUT_CHANNEL_ID", constants.DEFAULT_CHANNEL_ID),
            payout_channel_code=_env("DOKU_PAYOUT_CHANNEL_CODE"),
            payout_account_no=_env("DOKU_PAYOUT_ACCOUNT_NO"),
            payout_agent_key=_env("DOKU_PAYOUT_AGENT_KEY"),
            sender_phone=_env("DOKU_SENDER_PHONE"),
            sender_first_name=_env("DOKU_SENDER_FIRST_NAME"),
            sender_last_name=_env("DOKU_SENDER_LAST_NAME"),
            sender_id_number=_env("DOKU_SENDER_ID_NUMBER"),
            sender_id_type=_env("DOKU_SENDER_ID_TYPE", constants.DEFAULT_SENDER_ID_TYPE).upper(),
            private_key_env=private_key_env,
        )

    def _require(self, **settings):
        missing = [name for name, value in settings.items() if not value]
        if missing:
            raise ProviderNotConfigured("Missing DOKU settings: " + ", ".join(missing))

    def require_checkout_credentials(self):
        self._require(DOKU_CLIENT_ID=self.client_id, DOKU_SECRET_KEY=self.secret_key)

    def require_order_settings(self):
        self._require(DOKU_NOTIFY_URL=self.notify_url)

    def require_payout_credentials(self):
        self._require(
            DOKU_PAYOUT_CLIENT_ID=self.payout_client_id,
            DOKU_PAYOUT_SECRET_KEY=self.payout_secret_key,
            **{self.private_key_env: self.private_key},
        )

    def require_transfer_settings(self):
        self._require(
            DOKU_SENDER_PHONE=self.sender_phone,
            DOKU_SENDER_FIRST_NAME=self.sender_first_name,
            DOKU_SENDER_ID_NUMBER=self.sender_id_number,
        )

    def require_balance_settings(self):
        self._require(DOKU_PAYOUT_ACCOUNT_NO=self.payout_account_no)

    def require_payout_callback_credentials(self):
        self._require(DOKU_PAYOUT_AGENT_KEY=self.payout_agent_key)
