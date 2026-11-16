from unittest import mock

from cryptography.hazmat.primitives import serialization
from unittest import TestCase

from payment_aggregator.exceptions import ProviderNotConfigured
from payment_aggregator.providers.dana.config import DanaConfig
from payment_aggregator.testing import key_pair


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
