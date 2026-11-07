"""
Rintisan credentials, read from the environment (never hardcoded).

RINTISAN_ENV              sandbox | production (default: sandbox)
RINTISAN_BASE_URL         optional override of the base URL
RINTISAN_CLIENT_ID        x-client-id
RINTISAN_API_KEY          x-api-key
RINTISAN_PRIVATE_KEY_PATH Classping RSA private key (PEM) used to sign requests
RINTISAN_PUBLIC_KEY_PATH  Rintisan RSA public key (PEM) used to verify callbacks
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


@dataclass(frozen=True)
class RintisanConfig:
    base_url: str
    client_id: str
    api_key: str
    private_key_path: str
    public_key_path: str
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
            private_key_path=os.environ.get("RINTISAN_PRIVATE_KEY_PATH", ""),
            public_key_path=os.environ.get("RINTISAN_PUBLIC_KEY_PATH", ""),
            callback_token=os.environ.get("RINTISAN_CALLBACK_TOKEN", ""),
            payer_email=os.environ.get("RINTISAN_PAYER_EMAIL") or constants.PAYER_EMAIL,
            require_transfer_callback_signature=_env_bool(
                "RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE", True
            ),
        )

    def require_request_credentials(self):
        missing = [
            name
            for name, value in (
                ("RINTISAN_CLIENT_ID", self.client_id),
                ("RINTISAN_API_KEY", self.api_key),
                ("RINTISAN_PRIVATE_KEY_PATH", self.private_key_path),
            )
            if not value
        ]
        if missing:
            raise ProviderNotConfigured("Missing Rintisan settings: " + ", ".join(missing))

    def require_callback_credentials(self):
        missing = [
            name
            for name, value in (
                ("RINTISAN_CLIENT_ID", self.client_id),
                ("RINTISAN_PUBLIC_KEY_PATH", self.public_key_path),
            )
            if not value
        ]
        if missing:
            raise ProviderNotConfigured("Missing Rintisan settings: " + ", ".join(missing))
