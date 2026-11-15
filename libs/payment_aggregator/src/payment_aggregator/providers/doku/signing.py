"""
DOKU signatures.

Checkout and its notifications (Non-SNAP, HMAC-SHA256 with the Secret Key):

    Client-Id:{id}\\nRequest-Id:{id}\\nRequest-Timestamp:{ts}\\nRequest-Target:{path}
    [\\nDigest:{base64(sha256(body))}]          (POST only)
    Signature = "HMACSHA256=" + base64(hmac_sha256(secret, components))

  Request-Target is the DOKU path we call, or, for a notification, the path
  of OUR notification URL. Request-Timestamp is UTC ("...Z").

Kirim DOKU (SNAP):
  - B2B access token: X-SIGNATURE = base64(SHA256withRSA(private key,
    client_id + "|" + X-TIMESTAMP)).
  - Transactions: X-SIGNATURE = base64(hmac_sha512(client secret,
    METHOD:PATH:ACCESS_TOKEN:lowercase_hex(sha256(minified body)):X-TIMESTAMP)).
  X-TIMESTAMP is WIB ("YYYY-MM-DDTHH:mm:ss+07:00").
"""

import base64
import binascii
import datetime
import hashlib
import hmac
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from payment_aggregator.providers.doku import constants

WIB = datetime.timezone(datetime.timedelta(hours=constants.PROVIDER_UTC_OFFSET_HOURS), name="WIB")
HMAC_PREFIX = "HMACSHA256="


def _to_bytes(value):
    return value if isinstance(value, bytes) else value.encode("utf-8")


def minify(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


# --- Checkout (Non-SNAP) ----------------------------------------------------


def utc_timestamp(now=None):
    """Request-Timestamp: ISO 8601 UTC, e.g. 2026-11-15T03:00:00Z."""
    now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(body):
    return base64.b64encode(hashlib.sha256(_to_bytes(body)).digest()).decode("ascii")


def checkout_components(client_id, request_id, timestamp, target, body=None):
    parts = [
        "Client-Id:" + client_id,
        "Request-Id:" + request_id,
        "Request-Timestamp:" + timestamp,
        "Request-Target:" + target,
    ]
    if body is not None:
        parts.append("Digest:" + digest(body))
    return "\n".join(parts)


def checkout_signature(secret_key, client_id, request_id, timestamp, target, body=None):
    """``body`` None for GET (no Digest component)."""
    components = checkout_components(client_id, request_id, timestamp, target, body)
    mac = hmac.new(_to_bytes(secret_key), components.encode("utf-8"), hashlib.sha256).digest()
    return HMAC_PREFIX + base64.b64encode(mac).decode("ascii")


def verify_checkout_signature(secret_key, headers, targets, raw_body):
    """True when headers["signature"] signs the raw body for one of
    ``targets`` (the notification URL paths). ``headers`` keys are lowercase."""
    signature = headers.get("signature") or ""
    client_id = headers.get("client-id") or ""
    request_id = headers.get("request-id") or ""
    timestamp = headers.get("request-timestamp") or ""
    if not (signature and client_id and request_id and timestamp):
        return False
    return any(
        hmac.compare_digest(
            checkout_signature(secret_key, client_id, request_id, timestamp, target, raw_body), signature
        )
        for target in dict.fromkeys(t for t in targets if t)
    )


# --- Kirim DOKU (SNAP) ------------------------------------------------------


def snap_timestamp(now=None):
    """X-TIMESTAMP: YYYY-MM-DDTHH:mm:ss+07:00 (Jakarta time)."""
    now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(WIB)
    return now.strftime("%Y-%m-%dT%H:%M:%S+07:00")


def load_private_key(key_bytes):
    """PEM, or raw base64 of a PKCS#8 / PKCS#1 DER key."""
    text = key_bytes.decode("utf-8").strip()
    if "-----BEGIN" in text:
        return serialization.load_pem_private_key(key_bytes, password=None)
    try:
        der = base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Key is neither PEM nor base64")
    return serialization.load_der_private_key(der, password=None)


def token_signature(client_id, x_timestamp, private_key):
    signature = private_key.sign(
        "{}|{}".format(client_id, x_timestamp).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def snap_string_to_sign(method, path, access_token, body, x_timestamp):
    body_hash = hashlib.sha256(_to_bytes(body)).hexdigest().lower()
    return "{}:{}:{}:{}:{}".format(method.upper(), path, access_token, body_hash, x_timestamp)


def snap_signature(client_secret, method, path, access_token, body, x_timestamp):
    string_to_sign = snap_string_to_sign(method, path, access_token, body, x_timestamp)
    mac = hmac.new(_to_bytes(client_secret), string_to_sign.encode("utf-8"), hashlib.sha512).digest()
    return base64.b64encode(mac).decode("ascii")
