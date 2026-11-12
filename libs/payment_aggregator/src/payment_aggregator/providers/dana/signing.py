"""
DANA SNAP asymmetric signature (SHA256withRSA, PKCS#1 v1.5).

    stringToSign = METHOD + ":" + RELATIVE_PATH + ":"
                   + lowercase_hex(sha256(minified body)) + ":" + X-TIMESTAMP
    X-SIGNATURE  = base64(RSA_SHA256_sign(stringToSign))

Outgoing: hash and send the SAME minified string.
Incoming notifications: DANA signs the minified body; the raw body we receive
may or may not be minified, so verification tries the raw bytes and a
re-minified form (never trusting the parsed body without a valid signature).
"""

import base64
import binascii
import datetime
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from payment_aggregator.providers.dana import constants

WIB = datetime.timezone(datetime.timedelta(hours=constants.PROVIDER_UTC_OFFSET_HOURS), name="WIB")


def minify(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def timestamp(now=None):
    """X-TIMESTAMP: YYYY-MM-DDTHH:mm:ss+07:00 (Jakarta time)."""
    now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(WIB)
    return now.strftime("%Y-%m-%dT%H:%M:%S+07:00")


def _to_bytes(body):
    return body if isinstance(body, bytes) else body.encode("utf-8")


def string_to_sign(method, path, body, x_timestamp):
    body_hash = hashlib.sha256(_to_bytes(body)).hexdigest().lower()
    return "{}:{}:{}:{}".format(method.upper(), path, body_hash, x_timestamp)


def _der(key_bytes):
    """Raw base64 key data (no -----BEGIN----- lines, as DANA's dashboard shows
    keys) -> DER bytes; None when the key is PEM."""
    text = key_bytes.decode("utf-8").strip()
    if "-----BEGIN" in text:
        return None
    try:
        return base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Key is neither PEM nor base64")


def load_private_key(key_bytes):
    """PEM, or raw base64 of a PKCS#8 / PKCS#1 key."""
    der = _der(key_bytes)
    if der is None:
        return serialization.load_pem_private_key(key_bytes, password=None)
    return serialization.load_der_private_key(der, password=None)


def load_public_key(key_bytes):
    """PEM, or raw base64 of a SubjectPublicKeyInfo key."""
    der = _der(key_bytes)
    if der is None:
        return serialization.load_pem_public_key(key_bytes)
    return serialization.load_der_public_key(der)


def sign(method, path, body, x_timestamp, private_key):
    signature = private_key.sign(
        string_to_sign(method, path, body, x_timestamp).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _verify_one(method, path, body, x_timestamp, signature, public_key):
    try:
        public_key.verify(
            signature,
            string_to_sign(method, path, body, x_timestamp).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return False
    return True


def body_forms(raw_body):
    """The raw bytes, then minified re-serializations of them (deduplicated)."""
    raw = _to_bytes(raw_body)
    forms = [raw]
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return forms
    for ensure_ascii in (False, True):
        form = json.dumps(parsed, separators=(",", ":"), ensure_ascii=ensure_ascii).encode("utf-8")
        if form not in forms:
            forms.append(form)
    return forms


def verify(method, paths, raw_body, x_timestamp, signature_b64, public_key):
    """True when ``signature_b64`` is DANA's signature over the body for one of
    ``paths`` (the path we were called on, plus the SNAP standard path)."""
    if not signature_b64 or not x_timestamp:
        return False
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError):
        return False
    return any(
        _verify_one(method, path, body, x_timestamp, signature, public_key)
        for path in dict.fromkeys(p for p in paths if p)
        for body in body_forms(raw_body)
    )
