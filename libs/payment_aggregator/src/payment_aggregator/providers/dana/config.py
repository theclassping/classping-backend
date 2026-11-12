"""
DANA credentials. Build DanaConfig(...) directly, or read them from the
environment with DanaConfig.from_env() (never hardcode them):

DANA_ENV            sandbox | production (default: sandbox)
DANA_BASE_URL       optional override of the base URL
DANA_MERCHANT_ID    merchantId
DANA_CLIENT_ID      X-PARTNER-ID
DANA_CLIENT_SECRET  kept for symmetric-signature APIs (unused: asymmetric only)
DANA_CHANNEL_ID     CHANNEL-ID header (default 95221, the value DANA's SDKs send)
DANA_PRIVATE_KEY    our RSA private key, PEM text, signs requests
                    (variable name configurable: from_env(private_key_env=...))
DANA_PUBLIC_KEY     DANA's RSA public key, PEM text, verifies notifications
                    Both keys may use real newlines or literal \\n escapes.
DANA_NOTIFY_URL     our Finish Notify URL, sent with every order
DANA_RETURN_URL     page the payer returns to after paying (PAY_RETURN)
DANA_MCC            merchant category code (default: from_env(default_mcc=...))
"""

import os
from dataclasses import dataclass

from payment_aggregator.exceptions import ProviderNotConfigured
from payment_aggregator.providers.dana import constants
from payment_aggregator.utils import env_pem


@dataclass(frozen=True)
class DanaConfig:
    base_url: str
    merchant_id: str
    client_id: str
    channel_id: str
    private_key: str
    public_key: str
    notify_url: str = ""
    return_url: str = ""
    mcc: str = ""
    client_secret: str = ""
    timeout: int = constants.REQUEST_TIMEOUT_SECONDS
    # Only used to name the missing setting in ProviderNotConfigured.
    private_key_env: str = "DANA_PRIVATE_KEY"

    @classmethod
    def from_env(cls, private_key_env="DANA_PRIVATE_KEY", default_mcc="", default_notify_url="", default_return_url=""):
        env = os.environ.get("DANA_ENV", "sandbox").strip().lower()
        default_url = constants.BASE_URL_PRODUCTION if env == "production" else constants.BASE_URL_SANDBOX
        return cls(
            base_url=(os.environ.get("DANA_BASE_URL") or default_url).rstrip("/"),
            merchant_id=os.environ.get("DANA_MERCHANT_ID", "").strip(),
            client_id=os.environ.get("DANA_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("DANA_CLIENT_SECRET", "").strip(),
            channel_id=(os.environ.get("DANA_CHANNEL_ID") or constants.DEFAULT_CHANNEL_ID).strip(),
            private_key=env_pem(private_key_env),
            public_key=env_pem("DANA_PUBLIC_KEY"),
            notify_url=(os.environ.get("DANA_NOTIFY_URL") or default_notify_url).strip(),
            return_url=(os.environ.get("DANA_RETURN_URL") or default_return_url).strip(),
            mcc=(os.environ.get("DANA_MCC") or default_mcc).strip(),
            private_key_env=private_key_env,
        )

    def _require(self, **settings):
        missing = [name for name, value in settings.items() if not value]
        if missing:
            raise ProviderNotConfigured("Missing DANA settings: " + ", ".join(missing))

    def require_request_credentials(self):
        self._require(
            DANA_MERCHANT_ID=self.merchant_id,
            DANA_CLIENT_ID=self.client_id,
            DANA_CHANNEL_ID=self.channel_id,
            **{self.private_key_env: self.private_key},
        )

    def require_order_settings(self):
        self._require(DANA_NOTIFY_URL=self.notify_url, DANA_RETURN_URL=self.return_url, DANA_MCC=self.mcc)

    def require_callback_credentials(self):
        self._require(DANA_PUBLIC_KEY=self.public_key)
