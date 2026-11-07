import base64
import hashlib
import json

from django.test import SimpleTestCase

from apps.payment_aggregator.providers.rintisan import signing
from apps.payment_aggregator.tests.helpers import CLIENT_ID, key_pair


class MinifyTests(SimpleTestCase):
    def test_compact_and_slashes_not_escaped(self):
        body = signing.minify({"url": "https://a.b/c", "n": 1})
        self.assertEqual(body, '{"url":"https://a.b/c","n":1}')

    def test_unicode_kept_as_is(self):
        self.assertEqual(signing.minify({"name": "Sekolah Ñ"}), '{"name":"Sekolah Ñ"}')


class StringToSignTests(SimpleTestCase):
    def test_format_client_id_colon_lower_hex(self):
        body = '{"a":1}'
        expected = CLIENT_ID + ":" + hashlib.sha256(body.encode()).hexdigest()
        self.assertEqual(signing.string_to_sign(CLIENT_ID, body), expected)
        self.assertEqual(signing.string_to_sign(CLIENT_ID, body.encode()), expected)


class SignVerifyTests(SimpleTestCase):
    def setUp(self):
        self.private_key, self.public_key = key_pair("classping")

    def test_round_trip(self):
        body = signing.minify({"trx_id": "PPI-1"})
        signature = signing.sign(CLIENT_ID, body, self.private_key)
        base64.b64decode(signature, validate=True)
        self.assertTrue(signing.verify(CLIENT_ID, body.encode(), signature, self.public_key))

    def test_raw_body_with_unicode_escapes_verifies_only_as_received(self):
        # Rintisan may send \uXXXX escapes (e.g. qr_name); re-serializing would
        # change the bytes and break the signature.
        raw = b'{"qr_name":"Toko \\u00d1","total_amount":15000}'
        signature = signing.sign(CLIENT_ID, raw, self.private_key)
        self.assertTrue(signing.verify(CLIENT_ID, raw, signature, self.public_key))

        reserialized = signing.minify(json.loads(raw)).encode("utf-8")
        self.assertNotEqual(raw, reserialized)
        self.assertFalse(signing.verify(CLIENT_ID, reserialized, signature, self.public_key))

    def test_tampered_body_fails(self):
        signature = signing.sign(CLIENT_ID, b'{"a":1}', self.private_key)
        self.assertFalse(signing.verify(CLIENT_ID, b'{"a":2}', signature, self.public_key))

    def test_wrong_client_id_fails(self):
        signature = signing.sign(CLIENT_ID, b"{}", self.private_key)
        self.assertFalse(signing.verify("other", b"{}", signature, self.public_key))

    def test_wrong_key_fails(self):
        _, other_public = key_pair("rintisan")
        signature = signing.sign(CLIENT_ID, b"{}", self.private_key)
        self.assertFalse(signing.verify(CLIENT_ID, b"{}", signature, other_public))

    def test_missing_or_non_base64_signature_fails(self):
        self.assertFalse(signing.verify(CLIENT_ID, b"{}", "", self.public_key))
        self.assertFalse(signing.verify(CLIENT_ID, b"{}", "not base64!!", self.public_key))
