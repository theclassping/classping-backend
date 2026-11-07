from decimal import Decimal

from django.test import SimpleTestCase

from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator.aggregator import set_provider
from apps.payment_aggregator.base import BillingStatus
from apps.payment_aggregator.exceptions import ChannelNotAvailable
from apps.payment_aggregator.providers.rintisan.provider import RintisanProvider
from apps.payment_aggregator.tests.helpers import FakeResponse, make_provider
from apps.payment_aggregator.tests.test_rintisan_provider import BILLING_REQUEST, CREATE_VA_OK


class PaymentAggregatorFacadeTests(SimpleTestCase):
    def setUp(self):
        self.provider, self.session = make_provider(FakeResponse(body=CREATE_VA_OK))
        set_provider(self.provider)
        self.addCleanup(set_provider, None)

    def test_default_provider_is_rintisan(self):
        set_provider(None)
        self.assertIsInstance(
            __import__("apps.payment_aggregator.aggregator", fromlist=["get_provider"]).get_provider(),
            RintisanProvider,
        )

    def test_create_billing_delegates_to_provider(self):
        result = PaymentAggregator.create_billing(BILLING_REQUEST)
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(len(self.session.calls), 1)

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
        rules = PaymentAggregator.get_withdrawal_rules()
        self.assertEqual(rules.min_amount, Decimal("22500"))
        self.assertEqual(rules.max_amount, Decimal("250002500"))

    def test_bank_codes_exclude_ewallets(self):
        self.assertTrue(PaymentAggregator.is_supported_bank("BCA"))
        for code in ("GOPAY", "OVO", "DANA", "SHOPEEPAY", "LINKAJA"):
            self.assertFalse(PaymentAggregator.is_supported_bank(code), msg=code)

    def test_payment_deadline_days(self):
        self.assertEqual(PaymentAggregator.get_payment_deadline_days(), 1)
