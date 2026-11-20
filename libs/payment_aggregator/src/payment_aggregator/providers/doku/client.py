"""
Low-level HTTP client for DOKU: Checkout (Non-SNAP) and Kirim DOKU (SNAP,
with a cached B2B access token).

Business errors come back as HTTP 4xx with a JSON body; those bodies are
returned (with the HTTP status) to the mapper. Only transport failures and
unparseable bodies raise here.
"""

import logging
import secrets
import threading
import time
import uuid

import requests

from payment_aggregator.exceptions import ProviderAccessDenied, ProviderUnavailable
from payment_aggregator.providers.doku import constants, signing
from payment_aggregator.utils import safe_response_preview

logger = logging.getLogger(__name__)


def external_id():
    """X-EXTERNAL-ID: numeric, unique per day (ms timestamp + 6 random digits)."""
    return "{}{:06d}".format(int(time.time() * 1000), secrets.randbelow(10 ** 6))


class DokuClient:
    def __init__(self, config, private_key_loader, session=None, clock=time.monotonic):
        self.config = config
        self._private_key_loader = private_key_loader
        self.session = session or requests.Session()
        self._clock = clock
        self._token = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    # --- transport ---------------------------------------------------------

    def _send(self, method, path, headers, body=None):
        url = self.config.base_url + path
        kwargs = {"timeout": self.config.timeout, "headers": headers}
        if body is not None:
            kwargs["data"] = body.encode("utf-8")
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            logger.warning("DOKU %s %s failed: %s", method, path, exc)
            raise ProviderUnavailable("DOKU request failed") from exc
        try:
            data = response.json()
        except ValueError:
            data = None
        logger.info(
            "DOKU %s %s response: HTTP %s body=%r",
            method, path, response.status_code, safe_response_preview(response),
        )
        return response.status_code, data

    # --- Checkout (Non-SNAP) -------------------------------------------------

    def checkout_headers(self, target, body=None, now=None):
        self.config.require_checkout_credentials()
        request_id = str(uuid.uuid4())
        timestamp = signing.utc_timestamp(now)
        headers = {
            "Client-Id": self.config.client_id,
            "Request-Id": request_id,
            "Request-Timestamp": timestamp,
            "Signature": signing.checkout_signature(
                self.config.secret_key, self.config.client_id, request_id, timestamp, target, body
            ),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        return headers

    def checkout_request(self, method, path, payload=None):
        """(HTTP status, JSON body or None). 5xx raise ProviderUnavailable."""
        body = signing.minify(payload) if payload is not None else None
        status, data = self._send(method, path, self.checkout_headers(path, body), body)
        if status >= 500:
            raise ProviderUnavailable("DOKU error (HTTP {})".format(status), raw=data)
        if status in (401, 403):
            raise ProviderAccessDenied("DOKU denied the request (HTTP {})".format(status), raw=data)
        return status, data

    # --- Kirim DOKU (SNAP) ---------------------------------------------------

    def access_token(self, force=False):
        """Cached B2B token (valid 900 s), renewed shortly before it expires."""
        with self._token_lock:
            if not force and self._token and self._clock() < self._token_expires_at:
                return self._token
            self.config.require_payout_credentials()
            x_timestamp = signing.snap_timestamp()
            headers = {
                "Content-Type": "application/json",
                "X-CLIENT-KEY": self.config.payout_client_id,
                "X-TIMESTAMP": x_timestamp,
                "X-SIGNATURE": signing.token_signature(
                    self.config.payout_client_id, x_timestamp, self._private_key_loader()
                ),
            }
            status, data = self._send(
                "POST", constants.PATH_ACCESS_TOKEN, headers, signing.minify({"grantType": "client_credentials"})
            )
            data = data if isinstance(data, dict) else {}
            if str(data.get("responseCode") or "") != constants.RESPONSE_TOKEN_SUCCESS or not data.get("accessToken"):
                if status in (401, 403):
                    raise ProviderAccessDenied(
                        "DOKU refused the access token request ({})".format(data.get("responseCode") or status),
                        provider_message=str(data.get("responseMessage") or ""),
                        raw=data,
                    )
                raise ProviderUnavailable("DOKU access token failed (HTTP {})".format(status), raw=data)
            try:
                lifetime = int(data.get("expiresIn") or 900)
            except (TypeError, ValueError):
                lifetime = 900
            self._token = str(data["accessToken"])
            self._token_expires_at = self._clock() + max(lifetime - constants.TOKEN_REFRESH_MARGIN_SECONDS, 0)
            return self._token

    def snap_headers(self, path, body, access_token, now=None):
        x_timestamp = signing.snap_timestamp(now)
        return {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + access_token,
            "X-PARTNER-ID": self.config.payout_client_id,
            "X-EXTERNAL-ID": external_id(),
            "X-TIMESTAMP": x_timestamp,
            "X-SIGNATURE": signing.snap_signature(
                self.config.payout_secret_key, "POST", path, access_token, body, x_timestamp
            ),
            "CHANNEL-ID": self.config.payout_channel_id,
        }

    def snap_post(self, path, payload):
        """JSON body carrying responseCode. A rejected token (401xx01) is
        renewed and the request sent once more (DOKU did not process it)."""
        body = signing.minify(payload)
        for attempt in (1, 2):
            token = self.access_token(force=attempt == 2)
            status, data = self._send("POST", path, self.snap_headers(path, body, token), body)
            if not isinstance(data, dict) or not data.get("responseCode"):
                raise ProviderUnavailable("Unexpected DOKU response (HTTP {})".format(status), raw=data)
            code = str(data["responseCode"])
            if attempt == 1 and code.startswith("401") and code.endswith("01"):
                continue
            return data
        return data
