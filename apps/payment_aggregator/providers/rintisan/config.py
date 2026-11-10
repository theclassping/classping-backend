"""
Rintisan credentials, read from the environment (never hardcoded).

RINTISAN_ENV              sandbox | production (default: sandbox)
RINTISAN_BASE_URL         optional override of the base URL
RINTISAN_CLIENT_ID        x-client-id
RINTISAN_API_KEY          x-api-key
CLASSPING_PRIVATE_KEY     Classping RSA private key, PEM text, used to sign requests
RINTISAN_PUBLIC_KEY       Rintisan RSA public key, PEM text, used to verify callbacks
                          Both keys may use real newlines or literal \\n escapes.
RINTISAN_CALLBACK_TOKEN   static x-callback-token expected on callbacks
RINTISAN_PAYER_EMAIL      to_email sent on every billing (default: constants.PAYER_EMAIL)
RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE
                          true | false (default: true). Disbursement callback
                          signing is optional per account at Rintisan.
"""

import os
from dataclasses import dataclass

from apps.payment_aggregator.exceptions import ProviderNotConfigured
from apps.payment_aggregator.providers.rintisan import constants


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_pem(name):
    """PEM text from the environment; literal \\n escapes become newlines."""
    return os.environ.get(name, "").strip().replace("\\n", "\n")


@dataclass(frozen=True)
class RintisanConfig:
    base_url: str
    client_id: str
    api_key: str
    private_key: str
    public_key: str
    callback_token: str
    payer_email: str = constants.PAYER_EMAIL
    require_transfer_callback_signature: bool = True
    timeout: int = constants.REQUEST_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls):
        env = os.environ.get("RINTISAN_ENV", "sandbox").strip().lower()
        default_url = (
            constants.BASE_URL_PRODUCTION
            if env == "production"
            else constants.BASE_URL_SANDBOX
        )
        return cls(
            base_url=(os.environ.get("RINTISAN_BASE_URL") or default_url).rstrip("/"),
            client_id=os.environ.get("RINTISAN_CLIENT_ID", ""),
            api_key=os.environ.get("RINTISAN_API_KEY", ""),
            private_key=_env_pem("CLASSPING_PRIVATE_KEY"),
            public_key=_env_pem("RINTISAN_PUBLIC_KEY"),
            callback_token=os.environ.get("RINTISAN_CALLBACK_TOKEN", ""),
            payer_email=os.environ.get("RINTISAN_PAYER_EMAIL") or constants.PAYER_EMAIL,
            require_transfer_callback_signature=_env_bool(
                "RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE", True
            ),
        )

    def _require(self, **settings):
        missing = [name for name, value in settings.items() if not value]
        if missing:
            raise ProviderNotConfigured("Missing Rintisan settings: " + ", ".join(missing))

    def require_api_credentials(self):
        """Unsigned requests (GET /balance)."""
        self._require(RINTISAN_CLIENT_ID=self.client_id, RINTISAN_API_KEY=self.api_key)

    def require_request_credentials(self):
        """Signed requests."""
        self._require(
            RINTISAN_CLIENT_ID=self.client_id,
            RINTISAN_API_KEY=self.api_key,
            CLASSPING_PRIVATE_KEY=self.private_key,
        )

    def require_callback_credentials(self):
        self._require(
            RINTISAN_CLIENT_ID=self.client_id,
            RINTISAN_PUBLIC_KEY=self.public_key,
        )
