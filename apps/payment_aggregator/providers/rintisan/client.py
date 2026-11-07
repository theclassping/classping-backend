"""
Low-level HTTP client for Rintisan.

Only transport concerns live here: signing, headers, timeouts, HTTP 403 and
JSON decoding. Interpreting ``response_code`` is done in mapper.py.
"""

import logging

import requests

from apps.payment_aggregator.exceptions import (
    ProviderAccessDenied,
    ProviderUnavailable,
)
from apps.payment_aggregator.providers.rintisan import signing

logger = logging.getLogger(__name__)


class RintisanClient:
    def __init__(self, config, private_key_loader, session=None):
        self.config = config
        self._private_key_loader = private_key_loader
        self.session = session or requests.Session()

    def _headers(self, signature=None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-client-id": self.config.client_id,
            "x-api-key": self.config.api_key,
        }
        if signature is not None:
            headers["x-signature"] = signature
        return headers

    def post(self, path, payload):
        self.config.require_request_credentials()
        body = signing.minify(payload)
        signature = signing.sign(self.config.client_id, body, self._private_key_loader())
        return self._send(
            "POST",
            path,
            data=body.encode("utf-8"),
            headers=self._headers(signature),
        )

    def get(self, path):
        """Unsigned GET (only /balance uses this)."""
        if not self.config.client_id or not self.config.api_key:
            self.config.require_request_credentials()
        return self._send("GET", path, headers=self._headers())

    def _send(self, method, path, **kwargs):
        url = self.config.base_url + path
        try:
            response = self.session.request(
                method, url, timeout=self.config.timeout, **kwargs
            )
        except requests.RequestException as exc:
            logger.warning("Rintisan %s %s failed: %s", method, path, exc)
            raise ProviderUnavailable("Rintisan request failed") from exc

        try:
            data = response.json()
        except ValueError:
            data = None

        if response.status_code == 403:
            message = data.get("message", "") if isinstance(data, dict) else ""
            logger.error("Rintisan %s %s denied: %s", method, path, message)
            raise ProviderAccessDenied(
                "Rintisan denied the request", provider_message=message, raw=data
            )

        if response.status_code >= 400 or not isinstance(data, dict):
            logger.warning(
                "Rintisan %s %s unexpected response: HTTP %s",
                method,
                path,
                response.status_code,
            )
            raise ProviderUnavailable(
                "Unexpected Rintisan response (HTTP {})".format(response.status_code),
                raw=data,
            )

        logger.info(
            "Rintisan %s %s -> HTTP %s response_code=%s",
            method,
            path,
            response.status_code,
            data.get("response_code"),
        )
        return data
