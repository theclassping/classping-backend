from unittest import mock

from cryptography.hazmat.primitives import serialization
from unittest import TestCase

from payment_aggregator.exceptions import ProviderNotConfigured
from payment_aggregator.providers.dana.config import DanaConfig
from payment_aggregator.providers.rintisan import signing
from payment_aggregator.providers.rintisan.config import RintisanConfig
from payment_aggregator.providers.rintisan.provider import RintisanProvider
from payment_aggregator.testing import CLIENT_ID, key_pair


def _private_pem():
    return key_pair("merchant")[0].private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def _public_pem():
    return key_pair("merchant")[1].public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


class KeysFromEnvTests(TestCase):
    def _provider(self, private_pem, public_pem):
        env = {
            "RINTISAN_CLIENT_ID": CLIENT_ID,
            "RINTISAN_API_KEY": "api-key",
            "RINTISAN_PRIVATE_KEY": private_pem,
            "RINTISAN_PUBLIC_KEY": public_pem,
        }
        with mock.patch.dict("os.environ", env, clear=True):
            return RintisanProvider()

    def _assert_round_trip(self, provider):
        body = b'{"amount":1000}'
        signature = signing.sign(CLIENT_ID, body, provider._load_private_key())
        self.assertTrue(
            signing.verify(CLIENT_ID, body, signature, provider._load_public_key())
        )

    def test_multiline_pem_values(self):
        self._assert_round_trip(self._provider(_private_pem(), _public_pem()))

    def test_single_line_pem_with_escaped_newlines(self):
        provider = self._provider(
            _private_pem().replace("\n", "\\n"),
            _public_pem().replace("\n", "\\n"),
        )
        self._assert_round_trip(provider)

    def test_missing_private_key_is_reported_by_name(self):
        env = {"RINTISAN_CLIENT_ID": CLIENT_ID, "RINTISAN_API_KEY": "api-key"}
        with mock.patch.dict("os.environ", env, clear=True):
            config = RintisanConfig.from_env()
        with self.assertRaisesRegex(ProviderNotConfigured, "RINTISAN_PRIVATE_KEY"):
            config.require_request_credentials()

    def test_private_key_variable_name_is_configurable(self):
        env = {
            "RINTISAN_CLIENT_ID": CLIENT_ID,
            "RINTISAN_API_KEY": "api-key",
            "MY_APP_PRIVATE_KEY": _private_pem(),
        }
        with mock.patch.dict("os.environ", env, clear=True):
            config = RintisanConfig.from_env(private_key_env="MY_APP_PRIVATE_KEY")
        self.assertIn("BEGIN PRIVATE KEY", config.private_key)
        config.require_request_credentials()

        with mock.patch.dict("os.environ", {"RINTISAN_CLIENT_ID": CLIENT_ID, "RINTISAN_API_KEY": "k"}, clear=True):
            config = RintisanConfig.from_env(private_key_env="MY_APP_PRIVATE_KEY")
        with self.assertRaisesRegex(ProviderNotConfigured, "MY_APP_PRIVATE_KEY"):
            config.require_request_credentials()

    def test_missing_public_key_is_reported_by_name(self):
        provider = self._provider(_private_pem(), "")
        with self.assertRaisesRegex(ProviderNotConfigured, "RINTISAN_PUBLIC_KEY"):
            provider._load_public_key()


class DanaConfigTests(TestCase):
    BASE_ENV = {"DANA_MERCHANT_ID": "merchant", "DANA_CLIENT_ID": "client"}

    def test_missing_private_key_is_reported_by_name(self):
        with mock.patch.dict("os.environ", self.BASE_ENV, clear=True):
            config = DanaConfig.from_env()
        with self.assertRaisesRegex(ProviderNotConfigured, "DANA_PRIVATE_KEY"):
            config.require_request_credentials()

    def test_private_key_variable_name_is_configurable(self):
        env = dict(self.BASE_ENV, MY_APP_DANA_KEY=_private_pem().replace("\n", "\\n"))
        with mock.patch.dict("os.environ", env, clear=True):
            config = DanaConfig.from_env(private_key_env="MY_APP_DANA_KEY")
        self.assertIn("BEGIN PRIVATE KEY", config.private_key)
        self.assertIn("\n", config.private_key)
        config.require_request_credentials()

        with mock.patch.dict("os.environ", self.BASE_ENV, clear=True):
            config = DanaConfig.from_env(private_key_env="MY_APP_DANA_KEY")
        with self.assertRaisesRegex(ProviderNotConfigured, "MY_APP_DANA_KEY"):
            config.require_request_credentials()
