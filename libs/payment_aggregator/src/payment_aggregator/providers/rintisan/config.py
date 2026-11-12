"""
Rintisan credentials. Build RintisanConfig(...) directly, or read them from
the environment with RintisanConfig.from_env() (never hardcode them):

RINTISAN_ENV              sandbox | production (default: sandbox)
RINTISAN_BASE_URL         optional override of the base URL
RINTISAN_CLIENT_ID        x-client-id
RINTISAN_API_KEY          x-api-key
RINTISAN_PRIVATE_KEY      our RSA private key, PEM text, used to sign requests
                          (variable name configurable: from_env(private_key_env=...))
RINTISAN_PUBLIC_KEY       Rintisan RSA public key, PEM text, used to verify callbacks
                          Both keys may use real newlines or literal \\n escapes.
RINTISAN_CALLBACK_TOKEN   static x-callback-token expected on callbacks
RINTISAN_PAYER_EMAIL      to_email sent on every billing instead of the payer's
                          own email (default: from_env(default_payer_email=...);
                          empty = send BillingRequest.payer_email)
RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE
                          true | false (default: true). Disbursement callback
                          signing is optional per account at Rintisan.
"""

import os
from dataclasses import dataclass

from payment_aggregator.exceptions import ProviderNotConfigured
from payment_aggregator.providers.rintisan import constants


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
    payer_email: str = ""
    require_transfer_callback_signature: bool = True
    timeout: int = constants.REQUEST_TIMEOUT_SECONDS
    # Only used to name the missing setting in ProviderNotConfigured.
    private_key_env: str = "RINTISAN_PRIVATE_KEY"

    @classmethod
    def from_env(cls, private_key_env="RINTISAN_PRIVATE_KEY", default_payer_email=""):
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
            private_key=_env_pem(private_key_env),
            public_key=_env_pem("RINTISAN_PUBLIC_KEY"),
            callback_token=os.environ.get("RINTISAN_CALLBACK_TOKEN", ""),
            payer_email=os.environ.get("RINTISAN_PAYER_EMAIL") or default_payer_email,
            require_transfer_callback_signature=_env_bool(
                "RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE", True
            ),
            private_key_env=private_key_env,
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
            **{self.private_key_env: self.private_key},
        )

    def require_callback_credentials(self):
        self._require(
            RINTISAN_CLIENT_ID=self.client_id,
            RINTISAN_PUBLIC_KEY=self.public_key,
        )
