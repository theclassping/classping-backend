"""
Low-level HTTP client for DANA (SNAP headers, signing, timeouts, JSON).

DANA answers business errors with HTTP 4xx and a JSON body carrying
``responseCode``; those bodies are returned to the mapper. Only transport
failures and bodies without ``responseCode`` raise here.
"""

import logging
import secrets

import requests

from payment_aggregator.exceptions import ProviderUnavailable
from payment_aggregator.providers.dana import signing
from payment_aggregator.utils import safe_preview, safe_response_preview

logger = logging.getLogger(__name__)


def _debug_logging_enabled():
    """DANA payload and transport logs are for local debugging only."""
    try:
        from django.conf import settings

        return settings.configured and settings.DEBUG
    except ImportError:
        return False


# Never logged: the signature (and any auth token) would let a log reader
# replay or forge requests.
_UNLOGGED_HEADERS = frozenset({"X-SIGNATURE", "AUTHORIZATION", "AUTHORIZATION-CUSTOMER"})


def loggable_headers(headers):
    """Request headers safe to log (what DANA support asks for to trace a call)."""
    return {name: value for name, value in headers.items() if name.upper() not in _UNLOGGED_HEADERS}


def external_id():
    """X-EXTERNAL-ID: unique per day, 36 chars max. Numeric (32 random digits,
    as in DANA's samples): DANA recommends it and some channels reject
    non-numeric ids."""
    return "{:032d}".format(secrets.randbelow(10**32))


class DanaClient:
    def __init__(self, config, private_key_loader, session=None):
        self.config = config
        self._private_key_loader = private_key_loader
        self.session = session or requests.Session()

    def signed_request(self, path, payload, now=None):
        """(url, headers, body) for a signed POST, without sending it."""
        self.config.require_request_credentials()
        body = signing.minify(payload)
        x_timestamp = signing.timestamp(now)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-TIMESTAMP": x_timestamp,
            "X-SIGNATURE": signing.sign("POST", path, body, x_timestamp, self._private_key_loader()),
            "X-PARTNER-ID": self.config.client_id,
            "X-EXTERNAL-ID": external_id(),
            "CHANNEL-ID": self.config.channel_id,
        }
        return self.config.base_url + path, headers, body

    def post(self, path, payload, timeout=None):
        url, headers, body = self.signed_request(path, payload)
        # X-EXTERNAL-ID / X-TIMESTAMP let DANA support trace the request;
        # the signature is never logged and the payer phone is masked.
        external_id = headers["X-EXTERNAL-ID"]
        debug_logging = _debug_logging_enabled()
        if debug_logging:
            logger.info(
                "DANA POST %s request: external_id=%s timestamp=%s url=%s headers=%s body=%r",
                path,
                external_id,
                headers["X-TIMESTAMP"],
                url,
                loggable_headers(headers),
                safe_preview(body, limit=4000),
            )
        try:
            response = self.session.request(
                "POST", url, timeout=timeout or self.config.timeout, data=body.encode("utf-8"), headers=headers
            )
        except requests.RequestException as exc:
            if debug_logging:
                logger.warning("DANA POST %s failed (external_id=%s): %s", path, external_id, exc)
            raise ProviderUnavailable("DANA request failed") from exc

        try:
            data = response.json()
        except ValueError:
            data = None

        if debug_logging:
            logger.info(
                "DANA POST %s response: external_id=%s HTTP %s body=%r",
                path,
                external_id,
                response.status_code,
                safe_response_preview(response),
            )

        if not isinstance(data, dict) or not data.get("responseCode"):
            raise ProviderUnavailable(
                "Unexpected DANA response (HTTP {})".format(response.status_code), raw=data
            )
        return data
