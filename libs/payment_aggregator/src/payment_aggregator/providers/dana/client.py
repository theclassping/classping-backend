"""
Low-level HTTP client for DANA (SNAP headers, signing, timeouts, JSON).

DANA answers business errors with HTTP 4xx and a JSON body carrying
``responseCode``; those bodies are returned to the mapper. Only transport
failures and bodies without ``responseCode`` raise here.
"""

import logging
import uuid

import requests

from payment_aggregator.exceptions import ProviderUnavailable
from payment_aggregator.providers.dana import signing
from payment_aggregator.providers.rintisan.client import _safe_response_preview

logger = logging.getLogger(__name__)


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
            # Unique per day; 36 chars max.
            "X-EXTERNAL-ID": uuid.uuid4().hex,
            "CHANNEL-ID": self.config.channel_id,
        }
        return self.config.base_url + path, headers, body

    def post(self, path, payload):
        url, headers, body = self.signed_request(path, payload)
        try:
            response = self.session.request(
                "POST", url, timeout=self.config.timeout, data=body.encode("utf-8"), headers=headers
            )
        except requests.RequestException as exc:
            logger.warning("DANA POST %s failed: %s", path, exc)
            raise ProviderUnavailable("DANA request failed") from exc

        try:
            data = response.json()
        except ValueError:
            data = None

        logger.info(
            "DANA POST %s response: HTTP %s body=%r",
            path,
            response.status_code,
            _safe_response_preview(response),
        )

        if not isinstance(data, dict) or not data.get("responseCode"):
            raise ProviderUnavailable(
                "Unexpected DANA response (HTTP {})".format(response.status_code), raw=data
            )
        return data
