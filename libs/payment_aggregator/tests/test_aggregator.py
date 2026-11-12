from decimal import Decimal
from unittest import TestCase

from payment_aggregator import PaymentAggregator
from payment_aggregator.base import BillingStatus
from payment_aggregator.exceptions import ChannelNotAvailable
from payment_aggregator.testing import FakeResponse, make_provider

from tests.test_rintisan_provider import BILLING_REQUEST, CREATE_VA_OK

FEES = {"VABCA": Decimal("5000"), "CC": Decimal("2")}


class PaymentAggregatorTests(TestCase):
    def setUp(self):
        self.provider, self.session = make_provider(
            FakeResponse(body=CREATE_VA_OK),
            channel_fees=FEES,
            disbursement_fee=Decimal("2500"),
        )
        self.aggregator = PaymentAggregator(self.provider)

    def test_create_billing_delegates_to_provider(self):
        result = self.aggregator.create_billing(BILLING_REQUEST)
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(len(self.session.calls), 1)

    def test_only_channels_with_a_rate_are_offered(self):
        breakdowns = {b.channel_code: b for b in self.aggregator.get_channels(Decimal("50000"))}
        self.assertEqual(set(breakdowns), {"VABCA", "CC"})
        self.assertEqual(breakdowns["VABCA"].amount, Decimal("55000.00"))
        # 50000 * 100 / 98 = 51020.41 -> 51021
        self.assertEqual(breakdowns["CC"].amount, Decimal("51021.00"))

    def test_unpriced_channel_is_not_available(self):
        with self.assertRaises(ChannelNotAvailable):
            self.aggregator.calculate_transaction_fee("VABRI", Decimal("50000"))
        with self.assertRaises(ChannelNotAvailable):
            self.aggregator.calculate_transaction_fee("QRIS", Decimal("50000"))

    def test_withdrawal(self):
        result = self.aggregator.calculate_withdrawal(Decimal("150000"))
        self.assertEqual(result.fee, Decimal("2500.00"))
        self.assertEqual(result.transfer_amount, Decimal("147500.00"))

    def test_banks_exclude_ewallets(self):
        self.assertTrue(self.aggregator.is_supported_bank("BCA"))
        self.assertFalse(self.aggregator.is_supported_bank("GOPAY"))

    def test_two_aggregators_are_independent(self):
        other, _ = make_provider(channel_fees={"VABCA": Decimal("3000")})
        other_aggregator = PaymentAggregator(other)
        self.assertEqual(
            other_aggregator.calculate_transaction_fee("VABCA", Decimal("50000")).amount,
            Decimal("53000.00"),
        )
        self.assertEqual(
            self.aggregator.calculate_transaction_fee("VABCA", Decimal("50000")).amount,
            Decimal("55000.00"),
        )
        self.assertEqual(self.aggregator.provider_name(), "rintisan")
