"""
Rintisan request signing and callback verification (SHA256withRSA, PKCS#1 v1.5).

    stringToSign = "{client_id}:{lowercase_hex(sha256(body))}"
    x-signature  = base64(RSA_SHA256_sign(stringToSign))

Outgoing: body is the minified JSON we send (hash and send the SAME string).
Incoming callbacks: body is the raw bytes exactly as received (never re-serialize).
"""

import base64
import binascii
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def minify(payload):
    """Compact JSON, forward slashes not escaped (matches JSON_UNESCAPED_SLASHES)."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _to_bytes(body):
    if isinstance(body, bytes):
        return body
    return body.encode("utf-8")


def string_to_sign(client_id, body):
    body_hash = hashlib.sha256(_to_bytes(body)).hexdigest().lower()
    return "{}:{}".format(client_id, body_hash)


def load_private_key(pem_bytes):
    return serialization.load_pem_private_key(pem_bytes, password=None)


def load_public_key(pem_bytes):
    return serialization.load_pem_public_key(pem_bytes)


def sign(client_id, body, private_key):
    signature = private_key.sign(
        string_to_sign(client_id, body).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def verify(client_id, raw_body, signature_b64, public_key):
    """Return True when ``signature_b64`` is valid for ``raw_body``."""
    if not signature_b64:
        return False
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError):
        return False
    try:
        public_key.verify(
            signature,
            string_to_sign(client_id, raw_body).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return False
    return True
