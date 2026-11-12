"""
Classping's wiring of the payment_aggregator library: provider, contract
rates and credentials. Pricing numbers here must only change with the
Rintisan contract.
"""

import datetime
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase
from payment_aggregator.base import BillingRequest, BillingStatus
from payment_aggregator.exceptions import ChannelNotAvailable, ProviderNotConfigured
from payment_aggregator.providers.rintisan import RintisanProvider

from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator.aggregator import build_provider, get_provider, set_provider
from apps.payment_aggregator.testing import FakeResponse, make_provider

WIB = datetime.timezone(datetime.timedelta(hours=7))

BILLING_REQUEST = BillingRequest(
    reference_no="PAY-20261107-000501",
    channel_code="VABNI",
    amount=Decimal("154000.00"),
    invoice_date=datetime.date(2026, 11, 7),
    expires_at=datetime.datetime(2026, 11, 8, 10, 45, tzinfo=WIB),
    payer_name="Ibu Sari",
    payer_email="sari@example.com",
    payer_phone="6281234567890",
)

CREATE_VA_OK = {
    "response_code": "200",
    "message": "Bill details",
    "timestamp": "2026-11-07 10:16:02",
    "partner_trx_id": "PAY-20261107-000501",
    "trx_id": "PPI-261107-7654321FEDCBA",
    "payment_code": "988123456789",
    "total_amount": 154000,
    "payment_method": "VABNI",
    "rintisan_billing_link": "https://billing.rintisan.co.id/penagihan/abc",
    "bill_details": [],
}


class PaymentAggregatorFacadeTests(SimpleTestCase):
    def setUp(self):
        self.provider, self.session = make_provider(FakeResponse(body=CREATE_VA_OK))
        set_provider(self.provider)
        self.addCleanup(set_provider, None)

    def test_default_provider_is_rintisan(self):
        set_provider(None)
        self.assertIsInstance(get_provider(), RintisanProvider)

    def test_create_billing_delegates_to_provider(self):
        result = PaymentAggregator.create_billing(BILLING_REQUEST)
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(len(self.session.calls), 1)
        # Guardian email is never sent; Rintisan gets Classping's no-reply.
        self.assertEqual(self.session.last_json()["to_email"], "no-reply@hamanto.com")

    def test_channels_use_rintisan_pricing(self):
        breakdowns = {b.channel_code: b for b in PaymentAggregator.get_channels(Decimal("50000"))}
        self.assertEqual(
            set(breakdowns),
            {
                "VABCA", "VABRI", "VAMANDIRI", "VABNI", "VAPERMATA",
                "CC", "TOKOPEDIA CC", "TOKOPEDIA NON CC", "BLIBLI CC",
            },
        )
        self.assertEqual(breakdowns["VABCA"].amount, Decimal("55000.00"))
        self.assertEqual(breakdowns["VAPERMATA"].amount, Decimal("55000.00"))
        self.assertEqual(breakdowns["CC"].amount, Decimal("51021.00"))
        # 50000 * 100 / 98.25 = 50890.59 -> 50891
        self.assertEqual(breakdowns["TOKOPEDIA CC"].amount, Decimal("50891.00"))
        self.assertEqual(breakdowns["BLIBLI CC"].amount, Decimal("50891.00"))
        # 50000 * 100 / 99.5 = 50251.26 -> 50252
        self.assertEqual(breakdowns["TOKOPEDIA NON CC"].amount, Decimal("50252.00"))
        self.assertEqual(breakdowns["TOKOPEDIA CC"].payment_method, "e_commerce")

    def test_qris_not_offered(self):
        with self.assertRaises(ChannelNotAvailable):
            PaymentAggregator.calculate_transaction_fee("QRIS", Decimal("50000"))

    def test_withdrawal_uses_rintisan_rules(self):
        result = PaymentAggregator.calculate_withdrawal(Decimal("150000"))
        self.assertEqual(result.fee, Decimal("2500.00"))
        self.assertEqual(result.transfer_amount, Decimal("147500.00"))
        self.assertEqual(PaymentAggregator.get_withdrawal_rules().fee, Decimal("2500"))

    def test_bank_codes_exclude_ewallets(self):
        self.assertTrue(PaymentAggregator.is_supported_bank("BCA"))
        for code in ("GOPAY", "OVO", "DANA", "SHOPEEPAY", "LINKAJA"):
            self.assertFalse(PaymentAggregator.is_supported_bank(code), msg=code)

    def test_mock_patch_on_facade_is_undone(self):
        with mock.patch(
            "apps.payment_aggregator.PaymentAggregator.get_balance", return_value="patched"
        ):
            self.assertEqual(PaymentAggregator.get_balance(), "patched")
        self.assertNotIn("get_balance", vars(PaymentAggregator))


class ClasspingProviderConfigTests(SimpleTestCase):
    """build_provider() reads Classping's production env vars and rates."""

    def test_reads_classping_private_key_and_payer_email(self):
        env = {
            "RINTISAN_CLIENT_ID": "cid",
            "RINTISAN_API_KEY": "key",
            "CLASSPING_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            provider = build_provider()
        self.assertEqual(
            provider.config.private_key,
            "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        )
        self.assertEqual(provider.config.payer_email, "no-reply@hamanto.com")
        self.assertIn("sandbox", provider.config.base_url)

    def test_missing_private_key_names_classping_variable(self):
        with mock.patch.dict(
            "os.environ", {"RINTISAN_CLIENT_ID": "cid", "RINTISAN_API_KEY": "key"}, clear=True
        ):
            provider = build_provider()
        with self.assertRaisesMessage(ProviderNotConfigured, "CLASSPING_PRIVATE_KEY"):
            provider.config.require_request_credentials()

    def test_payer_email_env_override(self):
        with mock.patch.dict("os.environ", {"RINTISAN_PAYER_EMAIL": "x@classping.com"}, clear=True):
            self.assertEqual(build_provider().config.payer_email, "x@classping.com")

    def test_rates(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            provider = build_provider()
        fees = {c.code: c.fee for c in provider.get_channels()}
        self.assertEqual(
            fees,
            {
                "VABCA": Decimal("5000"), "VABRI": Decimal("5000"), "VAMANDIRI": Decimal("5000"),
                "VABNI": Decimal("5000"), "VAPERMATA": Decimal("5000"),
                "CC": Decimal("2"),
                "TOKOPEDIA CC": Decimal("1.75"), "TOKOPEDIA NON CC": Decimal("0.5"),
                "BLIBLI CC": Decimal("1.75"),
            },
        )
        self.assertEqual(provider.get_withdrawal_rules().fee, Decimal("2500"))

    def test_classping_rules_live_in_their_apps(self):
        from payment_aggregator.providers.rintisan import constants as rintisan_constants

        from apps.payment_gateway import constants as gateway_constants

        self.assertEqual(gateway_constants.PAYMENT_DEADLINE_MINUTES, 60)
        self.assertFalse(hasattr(rintisan_constants, "PAYMENT_DEADLINE_MINUTES"))
