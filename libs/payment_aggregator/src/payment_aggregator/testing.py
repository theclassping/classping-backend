"""
Test helpers for applications using payment_aggregator: run a real provider
against canned HTTP responses, and sign / verify with throwaway RSA keys.
"""

import json
from functools import lru_cache

from cryptography.hazmat.primitives.asymmetric import rsa

from payment_aggregator.providers.rintisan.config import RintisanConfig
from payment_aggregator.providers.rintisan.provider import RintisanProvider

CLIENT_ID = "merchant-test"


@lru_cache(maxsize=None)
def key_pair(name):
    """Cached RSA key pairs: 'merchant' (our side) and 'rintisan' (theirs)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self._text = text
        self.headers = {"Content-Type": "application/json" if body is not None else "text/plain"}

    @property
    def text(self):
        if self._text is not None:
            return self._text
        if self._body is not None:
            return json.dumps(self._body)
        return ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """Records requests and returns queued responses (or raises queued errors)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, timeout=None, **kwargs):
        self.calls.append({"method": method, "url": url, "timeout": timeout, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def last_json(self):
        return json.loads(self.calls[-1]["data"].decode("utf-8"))


def make_config(**overrides):
    values = dict(
        base_url="https://api.sandbox.rintisan.co.id/api/v1/billing/payin/partner",
        client_id=CLIENT_ID,
        api_key="api-key",
        private_key="unused",
        public_key="unused",
        callback_token="callback-token",
        require_transfer_callback_signature=True,
    )
    values.update(overrides)
    return RintisanConfig(**values)


def make_provider(*responses, channel_fees=None, disbursement_fee=None, **config_overrides):
    """A real RintisanProvider talking to a FakeSession that returns ``responses``
    (FakeResponse objects, or exceptions to raise), with test key pairs loaded."""
    session = FakeSession(*responses)
    provider = RintisanProvider(
        config=make_config(**config_overrides),
        channel_fees=channel_fees,
        disbursement_fee=disbursement_fee,
        session=session,
    )
    provider._private_key = key_pair("merchant")[0]
    provider._public_key = key_pair("rintisan")[1]
    return provider, session
