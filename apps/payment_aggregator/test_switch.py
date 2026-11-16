"""PAYMENT_PROVIDER switching: new records use the active provider, existing
records keep using the provider stored on them."""

from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings
from payment_aggregator.base import BillingResult, BillingStatus
from payment_aggregator.exceptions import InvalidCallback, ProviderNotConfigured
from payment_aggregator.providers.dana import DanaProvider

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

    def callback_reply(self, event, result=None):
        return None


class ProviderSwitchTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(set_provider, None)

    @override_settings(PAYMENT_PROVIDER="dana")
    def test_active_provider_follows_setting(self):
        set_provider(None)
        self.assertIsInstance(get_provider(), DanaProvider)
        self.assertEqual(PaymentAggregator.provider_name(), "dana")

    @override_settings(PAYMENT_PROVIDER="nope")
    def test_unknown_provider_setting_raises(self):
        set_provider(None)
        with self.assertRaises(ProviderNotConfigured):
            PaymentAggregator.provider_name()

    def test_using_active_or_blank_is_the_active_aggregator(self):
        dana_provider, _ = make_provider()
        set_provider(dana_provider)
        self.assertIs(PaymentAggregator.using("dana"), PaymentAggregator)
        self.assertIs(PaymentAggregator.using(""), PaymentAggregator)

    def test_using_routes_to_the_stored_provider_after_a_switch(self):
        dana_provider, _ = make_provider()
        other = OtherProvider(billing=BillingResult("PAY-1", "OTH-1"))
        set_provider(other)  # switched: "other" is active now
        add_provider(dana_provider)

        self.assertEqual(PaymentAggregator.provider_name(), "other")
        self.assertIs(PaymentAggregator.using("dana").provider, dana_provider)
        self.assertIs(PaymentAggregator.using("other").provider, other)

    def test_using_unknown_provider_raises(self):
        set_provider(OtherProvider())
        with self.assertRaises(ProviderNotConfigured):
            PaymentAggregator.using("gone").get_billing_status("X")

    def test_parse_callback_finds_the_provider_that_signed_it(self):
        dana_provider, _ = make_provider()
        other = OtherProvider(billing=BillingResult("PAY-1", "OTH-1"))
        set_provider(dana_provider)
        add_provider(other)
        name, billing = parse_callback("parse_billing_callback", b"{}", {"X-Other-Token": "other-token"})
        self.assertEqual((name, billing.provider_trx_id), ("other", "OTH-1"))

    def test_parse_callback_rejects_a_body_no_provider_verifies(self):
        dana_provider, _ = make_provider()
        set_provider(dana_provider)
        add_provider(OtherProvider())
        with self.assertRaises(InvalidCallback):
            parse_callback("parse_billing_callback", b"{}", {})

    def test_parse_callback_reports_the_active_providers_reason(self):
        other = OtherProvider()
        set_provider(other)  # active, tried first
        dana_provider, _ = make_provider()
        add_provider(dana_provider)  # tried after it, rejects too
        with self.assertRaisesMessage(InvalidCallback, "not signed by other"):
            parse_callback("parse_billing_callback", b"{}", {})

    def test_parse_callback_with_provider_tries_only_that_one(self):
        dana_provider, _ = make_provider()
        set_provider(dana_provider)
        add_provider(OtherProvider(billing=BillingResult("PAY-1", "OTH-1")))
        with self.assertRaises(InvalidCallback):
            parse_callback("parse_billing_callback", b"{}", {"X-Other-Token": "other-token"}, provider="dana")


class ProviderModuleTests(SimpleTestCase):
    """Every module in apps/payment_aggregator/providers/ has the same shape."""

    def test_every_provider_module_exposes_the_contract(self):
        from apps.payment_aggregator import providers

        self.assertEqual(providers.names(), ("dana", "doku"))
        for name, module in providers.registry().items():
            with self.subTest(provider=name):
                self.assertEqual(module.NAME, name)
                self.assertIsInstance(module.CHANNEL_FEES, dict)
                self.assertTrue(hasattr(module, "DISBURSEMENT_FEE"))
                self.assertTrue(callable(module.build))

    def test_every_channel_code_fits_the_checkout_fields(self):
        from apps.payment_aggregator import providers
        from apps.payment_gateway.models import GatewayPayment
        from apps.payment_gateway.serializers import CheckoutRequestSerializer

        db_limit = GatewayPayment._meta.get_field("channel_code").max_length
        request_limit = CheckoutRequestSerializer().fields["channel"].max_length
        for name, module in providers.registry().items():
            for code in module.CHANNEL_FEES:
                with self.subTest(provider=name, channel=code):
                    self.assertLessEqual(len(code), db_limit)
                    self.assertLessEqual(len(code), request_limit)

    def test_dana_rates_include_vat(self):
        from apps.payment_aggregator.providers import dana

        self.assertEqual(dana.CHANNEL_FEES["VIRTUAL_ACCOUNT_BCA"], Decimal("2775"))
        self.assertEqual(dana.CHANNEL_FEES["NETWORK_PAY_PG_CARD"], Decimal("3.219"))
        self.assertEqual(dana.CHANNEL_FEES["NETWORK_PAY_PG_OVO"], Decimal("2.22"))
        self.assertNotIn("NETWORK_PAY_PG_QRIS", dana.CHANNEL_FEES)

    def test_every_dana_channel_except_qris_is_offered(self):
        from payment_aggregator.base import PaymentMethod
        from payment_aggregator.providers.dana import constants

        from apps.payment_aggregator.providers import dana

        self.assertEqual(set(dana.CHANNEL_FEES), set(constants.CHANNELS))
        for code in ("NETWORK_PAY_PG_OVO", "NETWORK_PAY_PG_GOPAY", "NETWORK_PAY_PG_SPAY", "NETWORK_PAY_PG_LINKAJA"):
            self.assertEqual(constants.CHANNELS[code]["method"], PaymentMethod.E_WALLET)
        self.assertEqual(dana.DISBURSEMENT_FEE, Decimal("2500"))

    def test_every_provider_uses_the_general_disbursement_fee(self):
        from apps.payment_aggregator import constants, providers

        self.assertEqual(constants.DISBURSEMENT_FEE, Decimal("2500"))
        for name in providers.names():
            with self.subTest(provider=name):
                self.assertEqual(providers.get(name).DISBURSEMENT_FEE, constants.DISBURSEMENT_FEE)

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


class DokuProviderModuleTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(set_provider, None)

    def test_doku_rates_include_vat(self):
        from apps.payment_aggregator.providers import doku

        self.assertEqual(doku.CHANNEL_FEES["VIRTUAL_ACCOUNT_BCA"], Decimal("4995"))
        self.assertEqual(doku.CHANNEL_FEES["VIRTUAL_ACCOUNT_BNI"], Decimal("4440"))
        self.assertEqual(doku.CHANNEL_FEES["CREDIT_CARD"], Decimal("3.108"))
        self.assertEqual(doku.CHANNEL_FLAT_FEES["CREDIT_CARD"], Decimal("2220"))
        self.assertNotIn("QRIS", doku.CHANNEL_FEES)
        self.assertEqual(doku.DISBURSEMENT_FEE, Decimal("2500"))
        # E-wallets: one public rate, or the top of DOKU's published range.
        self.assertEqual(doku.CHANNEL_FEES["EMONEY_DANA"], Decimal("1.665"))
        self.assertEqual(doku.CHANNEL_FEES["EMONEY_OVO"], Decimal("3.5298"))
        self.assertEqual(doku.CHANNEL_FEES["EMONEY_SHOPEE_PAY"], Decimal("4.44"))
        self.assertEqual(doku.CHANNEL_FEES["EMONEY_LINKAJA"], Decimal("3.885"))

    @override_settings(PAYMENT_PROVIDER="doku")
    def test_doku_e_wallets_are_grouped_as_e_wallet(self):
        set_provider(None)
        channels = {c.channel_code: c for c in PaymentAggregator.get_channels(Decimal("100000"))}
        self.assertEqual(channels["EMONEY_DANA"].payment_method, "e_wallet")
        # ceil(100000 * 100 / 98.335) = 101694
        self.assertEqual(channels["EMONEY_DANA"].amount, Decimal("101694.00"))

    @override_settings(PAYMENT_PROVIDER="doku")
    def test_doku_is_selectable_with_card_gross_up(self):
        from apps.payment_aggregator.providers import doku

        set_provider(None)
        self.assertEqual(PaymentAggregator.provider_name(), "doku")
        self.assertTrue(PaymentAggregator.provider.config.notify_url.endswith("/api/webhooks/payment/"))
        channels = {c.channel_code: c for c in PaymentAggregator.get_channels(Decimal("1000000"))}
        self.assertEqual(set(channels), set(doku.CHANNEL_FEES))
        self.assertEqual(channels["VIRTUAL_ACCOUNT_BNI"].amount, Decimal("1004440.00"))
        self.assertEqual(channels["CREDIT_CARD"].amount, Decimal("1034369.00"))
        withdrawal = PaymentAggregator.calculate_withdrawal(Decimal("100000"))
        self.assertEqual(withdrawal.transfer_amount, Decimal("97500.00"))
        # Saved payout accounts keep their Classping bank codes.
        self.assertTrue(PaymentAggregator.is_supported_bank("MANDIRI"))

    def test_disbursement_reply_echoes_transaction_id(self):
        from payment_aggregator.base import TransferResult, TransferStatus
        from payment_aggregator.testing import make_doku_provider

        from apps.payment_aggregator.aggregator import callback_reply

        provider, _ = make_doku_provider()
        set_provider(provider)
        result = TransferResult("WDR-1", "", TransferStatus.SUCCESS, raw={"transactionId": "DK0018353"})
        reply = callback_reply("doku", "disbursement", {"status": "ok"}, result=result)
        self.assertEqual(reply.body["transactionId"], "DK0018353")
        self.assertEqual(reply.body["responseCode"], "00")
        self.assertEqual(callback_reply("doku", "payment", {"status": "ok"}), {"status": "ok"})


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
