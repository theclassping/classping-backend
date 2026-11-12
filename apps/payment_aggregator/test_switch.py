"""PAYMENT_PROVIDER switching: new records use the active provider, existing
records keep using the provider stored on them."""

from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings
from payment_aggregator.base import BillingResult, BillingStatus
from payment_aggregator.exceptions import InvalidCallback, ProviderNotConfigured
from payment_aggregator.providers.rintisan import RintisanProvider

from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator.aggregator import add_provider, get_provider, parse_callback, set_provider
from apps.payment_aggregator.testing import make_provider


class OtherProvider:
    """Stand-in for a second aggregator (only what the tests call)."""

    name = "other"

    def __init__(self, billing=None):
        self.billing = billing
        self.calls = []

    def get_billing_status(self, provider_trx_id):
        self.calls.append(("get_billing_status", provider_trx_id))
        return self.billing

    def parse_billing_callback(self, raw_body, headers, request_path=""):
        if headers.get("X-Other-Token") != "other-token":
            raise InvalidCallback("not signed by other")
        return self.billing

    def callback_reply(self, event):
        return None


class ProviderSwitchTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(set_provider, None)

    @override_settings(PAYMENT_PROVIDER="rintisan")
    def test_active_provider_follows_setting(self):
        set_provider(None)
        self.assertIsInstance(get_provider(), RintisanProvider)
        self.assertEqual(PaymentAggregator.provider_name(), "rintisan")

    @override_settings(PAYMENT_PROVIDER="nope")
    def test_unknown_provider_setting_raises(self):
        set_provider(None)
        with self.assertRaises(ProviderNotConfigured):
            PaymentAggregator.provider_name()

    def test_using_active_or_blank_is_the_active_aggregator(self):
        rintisan, _ = make_provider()
        set_provider(rintisan)
        self.assertIs(PaymentAggregator.using("rintisan"), PaymentAggregator)
        self.assertIs(PaymentAggregator.using(""), PaymentAggregator)

    def test_using_routes_to_the_stored_provider_after_a_switch(self):
        rintisan, _ = make_provider()
        other = OtherProvider(billing=BillingResult("PAY-1", "OTH-1"))
        set_provider(other)  # switched: "other" is active now
        add_provider(rintisan)

        self.assertEqual(PaymentAggregator.provider_name(), "other")
        self.assertIs(PaymentAggregator.using("rintisan").provider, rintisan)
        self.assertIs(PaymentAggregator.using("other").provider, other)

    def test_using_unknown_provider_raises(self):
        set_provider(OtherProvider())
        with self.assertRaises(ProviderNotConfigured):
            PaymentAggregator.using("gone").get_billing_status("X")

    def test_parse_callback_finds_the_provider_that_signed_it(self):
        rintisan, _ = make_provider()
        other = OtherProvider(billing=BillingResult("PAY-1", "OTH-1"))
        set_provider(rintisan)
        add_provider(other)
        name, billing = parse_callback("parse_billing_callback", b"{}", {"X-Other-Token": "other-token"})
        self.assertEqual((name, billing.provider_trx_id), ("other", "OTH-1"))

    def test_parse_callback_rejects_a_body_no_provider_verifies(self):
        rintisan, _ = make_provider()
        set_provider(rintisan)
        add_provider(OtherProvider())
        with self.assertRaises(InvalidCallback):
            parse_callback("parse_billing_callback", b"{}", {})

    def test_parse_callback_with_provider_tries_only_that_one(self):
        rintisan, _ = make_provider()
        set_provider(rintisan)
        add_provider(OtherProvider(billing=BillingResult("PAY-1", "OTH-1")))
        with self.assertRaises(InvalidCallback):
            parse_callback("parse_billing_callback", b"{}", {"X-Other-Token": "other-token"}, provider="rintisan")


class ProviderModuleTests(SimpleTestCase):
    """Every module in apps/payment_aggregator/providers/ has the same shape."""

    def test_every_provider_module_exposes_the_contract(self):
        from apps.payment_aggregator import providers

        self.assertEqual(providers.names(), ("rintisan", "dana"))
        for name, module in providers.registry().items():
            with self.subTest(provider=name):
                self.assertEqual(module.NAME, name)
                self.assertIsInstance(module.CHANNEL_FEES, dict)
                self.assertTrue(hasattr(module, "DISBURSEMENT_FEE"))
                self.assertTrue(callable(module.build))

    def test_dana_rates_include_vat(self):
        from apps.payment_aggregator.providers import dana

        self.assertEqual(dana.CHANNEL_FEES["VIRTUAL_ACCOUNT_BCA"], Decimal("2775"))
        self.assertEqual(dana.CHANNEL_FEES["NETWORK_PAY_PG_CARD"], Decimal("3.219"))
        self.assertNotIn("NETWORK_PAY_PG_QRIS", dana.CHANNEL_FEES)
        self.assertIsNone(dana.DISBURSEMENT_FEE)

    @override_settings(PAYMENT_PROVIDER="dana")
    def test_dana_is_selectable_and_offers_only_priced_channels(self):
        from apps.payment_aggregator.providers import dana

        set_provider(None)
        with mock.patch.dict("os.environ", {"DANA_RETURN_URL": "https://app.example.com/pay/finish"}):
            self.assertEqual(PaymentAggregator.provider_name(), "dana")
            config = PaymentAggregator.provider.config
        self.assertEqual(config.mcc, "8211")
        self.assertTrue(config.notify_url.endswith("/api/webhooks/payment/"))
        priced = {c.channel_code for c in PaymentAggregator.get_channels(Decimal("100000"))}
        self.assertEqual(priced, set(dana.CHANNEL_FEES))


class DanaCurlCommandTests(SimpleTestCase):
    def test_prints_signed_order_without_sending(self):
        from io import StringIO

        from django.core.management import call_command
        from payment_aggregator.testing import make_dana_provider

        provider, session = make_dana_provider(channel_fees={"VIRTUAL_ACCOUNT_BCA": Decimal("2775")})
        out = StringIO()
        with mock.patch(
            "apps.payment_gateway.management.commands.dana_curl.build_provider", return_value=provider
        ):
            call_command("dana_curl", stdout=out)
        text = out.getvalue()
        self.assertIn("/payment-gateway/v1.0/debit/payment-host-to-host.htm", text)
        self.assertIn("X-SIGNATURE: ", text)
        self.assertIn('"partnerReferenceNo":"TEST-', text)
        self.assertEqual(session.calls, [])
