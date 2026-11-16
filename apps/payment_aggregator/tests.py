"""
Classping's wiring of the payment_aggregator library: provider, contract
rates and credentials. Pricing numbers here must only change with the
provider contracts.
"""

import datetime
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase
from payment_aggregator.base import BillingRequest, BillingStatus
from payment_aggregator.exceptions import ChannelNotAvailable, ProviderNotConfigured
from payment_aggregator.providers.dana import DanaProvider

from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator.aggregator import build_provider, get_provider, set_provider
from apps.payment_aggregator.testing import FakeResponse, make_provider

WIB = datetime.timezone(datetime.timedelta(hours=7))

BILLING_REQUEST = BillingRequest(
    reference_no="PAY-20261107-000501",
    channel_code="VIRTUAL_ACCOUNT_BNI",
    amount=Decimal("152775.00"),
    invoice_date=datetime.date(2026, 11, 7),
    expires_at=datetime.datetime(2026, 11, 8, 10, 45, tzinfo=WIB),
    payer_name="Ibu Sari",
    payer_email="sari@example.com",
    payer_phone="6281234567890",
)

CREATE_OK = {
    "responseCode": "2005400",
    "responseMessage": "Successful",
    "referenceNo": "2026110711212800100166",
    "partnerReferenceNo": "PAY-20261107-000501",
    "webRedirectUrl": "https://m.sandbox.dana.id/n/cashier/new/checkout?bizNo=1",
    "additionalInfo": {"paymentCode": "8808123456789"},
}


class PaymentAggregatorFacadeTests(SimpleTestCase):
    def setUp(self):
        self.provider, self.session = make_provider(FakeResponse(body=CREATE_OK))
        set_provider(self.provider)
        self.addCleanup(set_provider, None)

    def test_default_provider_is_dana(self):
        set_provider(None)
        self.assertIsInstance(get_provider(), DanaProvider)

    def test_create_billing_delegates_to_provider(self):
        result = PaymentAggregator.create_billing(BILLING_REQUEST)
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(len(self.session.calls), 1)
        # The guardian's email is never sent to the provider.
        self.assertNotIn("sari@example.com", self.session.calls[0]["data"].decode())

    def test_channels_use_dana_pricing(self):
        breakdowns = {b.channel_code: b for b in PaymentAggregator.get_channels(Decimal("50000"))}
        self.assertEqual(
            set(breakdowns),
            {
                "VIRTUAL_ACCOUNT_BCA", "VIRTUAL_ACCOUNT_BNI", "VIRTUAL_ACCOUNT_BRI",
                "VIRTUAL_ACCOUNT_MANDIRI", "VIRTUAL_ACCOUNT_PERMATA", "VIRTUAL_ACCOUNT_CIMB",
                "NETWORK_PAY_PG_CARD", "NETWORK_PAY_PG_OVO", "NETWORK_PAY_PG_GOPAY",
                "NETWORK_PAY_PG_SPAY", "NETWORK_PAY_PG_LINKAJA",
            },
        )
        self.assertEqual(breakdowns["VIRTUAL_ACCOUNT_BCA"].amount, Decimal("52775.00"))
        # 50000 * 100 / (100 - 3.219) = 51663.03 -> 51664
        self.assertEqual(breakdowns["NETWORK_PAY_PG_CARD"].amount, Decimal("51664.00"))
        # 50000 * 100 / (100 - 2.22) = 51135.20 -> 51136
        self.assertEqual(breakdowns["NETWORK_PAY_PG_OVO"].amount, Decimal("51136.00"))
        self.assertEqual(breakdowns["NETWORK_PAY_PG_OVO"].payment_method, "e_wallet")

    def test_qris_not_offered(self):
        with self.assertRaises(ChannelNotAvailable):
            PaymentAggregator.calculate_transaction_fee("NETWORK_PAY_PG_QRIS", Decimal("50000"))

    def test_withdrawal_uses_the_general_fee(self):
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

    def test_reads_classping_private_key(self):
        env = {
            "DANA_MERCHANT_ID": "mid",
            "DANA_CLIENT_ID": "cid",
            "CLASSPING_DANA_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            provider = build_provider()
        self.assertEqual(
            provider.config.private_key,
            "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        )
        self.assertIn("sandbox", provider.config.base_url)

    def test_missing_private_key_names_classping_variable(self):
        with mock.patch.dict("os.environ", {"DANA_MERCHANT_ID": "mid", "DANA_CLIENT_ID": "cid"}, clear=True):
            provider = build_provider()
        with self.assertRaisesMessage(ProviderNotConfigured, "CLASSPING_DANA_PRIVATE_KEY"):
            provider.config.require_request_credentials()

    def test_withdrawals_need_the_payout_phone(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            provider = build_provider()
        with self.assertRaisesMessage(ProviderNotConfigured, "DANA_PAYOUT_PHONE"):
            provider.get_withdrawal_rules()
        with mock.patch.dict("os.environ", {"DANA_PAYOUT_PHONE": "6281200000000"}, clear=True):
            self.assertEqual(build_provider().get_withdrawal_rules().fee, Decimal("2500"))

    def test_classping_rules_live_in_their_apps(self):
        from payment_aggregator.providers.dana import constants as dana_constants

        from apps.payment_gateway import constants as gateway_constants

        self.assertEqual(gateway_constants.PAYMENT_DEADLINE_MINUTES, 60)
        self.assertFalse(hasattr(dana_constants, "PAYMENT_DEADLINE_MINUTES"))
