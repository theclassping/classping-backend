from decimal import Decimal
from unittest import TestCase

from payment_aggregator import PaymentAggregator
from payment_aggregator.base import BillingStatus, RefundRequest
from payment_aggregator.exceptions import ChannelNotAvailable, OperationNotSupported
from payment_aggregator.testing import FakeResponse, make_dana_provider, make_doku_provider

from tests.test_dana_provider import CREATE_OK, billing_request

FEES = {"VIRTUAL_ACCOUNT_BCA": Decimal("5000"), "NETWORK_PAY_PG_CARD": Decimal("2")}


class PaymentAggregatorTests(TestCase):
    def setUp(self):
        self.provider, self.session = make_dana_provider(
            FakeResponse(body=CREATE_OK),
            channel_fees=FEES,
            disbursement_fee=Decimal("2500"),
        )
        self.aggregator = PaymentAggregator(self.provider)

    def test_create_billing_delegates_to_provider(self):
        result = self.aggregator.create_billing(billing_request())
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(len(self.session.calls), 1)

    def test_only_channels_with_a_rate_are_offered(self):
        breakdowns = {b.channel_code: b for b in self.aggregator.get_channels(Decimal("50000"))}
        self.assertEqual(set(breakdowns), {"VIRTUAL_ACCOUNT_BCA", "NETWORK_PAY_PG_CARD"})
        self.assertEqual(breakdowns["VIRTUAL_ACCOUNT_BCA"].amount, Decimal("55000.00"))
        # 50000 * 100 / 98 = 51020.41 -> 51021
        self.assertEqual(breakdowns["NETWORK_PAY_PG_CARD"].amount, Decimal("51021.00"))

    def test_provider_without_cancel_or_refund_says_so(self):
        doku, session = make_doku_provider()
        aggregator = PaymentAggregator(doku)
        self.assertFalse(aggregator.can_cancel_billing())
        self.assertFalse(aggregator.can_refund())
        with self.assertRaises(OperationNotSupported):
            aggregator.cancel_billing("PAY-1")
        with self.assertRaises(OperationNotSupported):
            aggregator.refund_billing(RefundRequest("PAY-1", "RF-1", Decimal("1000")))
        self.assertEqual(session.calls, [])
        self.assertTrue(self.aggregator.can_cancel_billing())
        self.assertTrue(self.aggregator.can_refund())

    def test_unpriced_channel_is_not_available(self):
        with self.assertRaises(ChannelNotAvailable):
            self.aggregator.calculate_transaction_fee("VIRTUAL_ACCOUNT_BRI", Decimal("50000"))
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
        other, _ = make_dana_provider(channel_fees={"VIRTUAL_ACCOUNT_BCA": Decimal("3000")})
        other_aggregator = PaymentAggregator(other)
        self.assertEqual(
            other_aggregator.calculate_transaction_fee("VIRTUAL_ACCOUNT_BCA", Decimal("50000")).amount,
            Decimal("53000.00"),
        )
        self.assertEqual(
            self.aggregator.calculate_transaction_fee("VIRTUAL_ACCOUNT_BCA", Decimal("50000")).amount,
            Decimal("55000.00"),
        )
        self.assertEqual(self.aggregator.provider_name(), "dana")
