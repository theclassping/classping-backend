from decimal import Decimal

from django.test import SimpleTestCase

from apps.payment_aggregator import fees
from apps.payment_aggregator.base import Channel, FeeType, PaymentMethod, WithdrawalRules
from apps.payment_aggregator.exceptions import (
    AmountBelowMinimum,
    ChannelNotAvailable,
    InvalidAmount,
)

VA = Channel(
    code="VABCA",
    name="BCA Virtual Account",
    method=PaymentMethod.VIRTUAL_ACCOUNT,
    fee_type=FeeType.FLAT,
    fee=Decimal("5000"),
    min_amount=Decimal("10000"),
)
CC = Channel(
    code="CC",
    name="Kartu Kredit",
    method=PaymentMethod.CREDIT_CARD,
    fee_type=FeeType.PERCENT,
    fee=Decimal("2"),
    min_amount=Decimal("10000"),
    max_amount=Decimal("100000000"),
)
RULES = WithdrawalRules(fee=Decimal("2500"))


class TransactionFeeTests(SimpleTestCase):
    def test_flat_fee_added_on_top(self):
        result = fees.calculate_transaction_fee(VA, Decimal("50000"))
        self.assertEqual(result.invoice_total, Decimal("50000.00"))
        self.assertEqual(result.transaction_fee, Decimal("5000.00"))
        self.assertEqual(result.amount, Decimal("55000.00"))
        self.assertEqual(result.payment_method, PaymentMethod.VIRTUAL_ACCOUNT)

    def test_percent_fee_is_grossed_up(self):
        result = fees.calculate_transaction_fee(CC, Decimal("50000"))
        # 50000 * 100 / 98 = 51020.41 -> 51021
        self.assertEqual(result.amount, Decimal("51021.00"))
        self.assertEqual(result.transaction_fee, Decimal("1021.00"))

        result = fees.calculate_transaction_fee(CC, Decimal("1000000"))
        self.assertEqual(result.amount, Decimal("1020409.00"))
        self.assertEqual(result.transaction_fee, Decimal("20409.00"))

    def test_gross_up_exact_division_not_rounded_up(self):
        self.assertEqual(fees.gross_up(Decimal("49000"), Decimal("2")), Decimal("50000"))

    def test_gross_up_net_never_below_invoice_total(self):
        for total in range(10000, 2000000, 7919):
            total = Decimal(total)
            amount = fees.calculate_transaction_fee(CC, total).amount
            net = amount * (Decimal("100") - CC.fee) / Decimal("100")
            self.assertGreaterEqual(net, total, msg=str(total))

    def test_invoice_total_with_cents_rounds_amount_up(self):
        result = fees.calculate_transaction_fee(VA, Decimal("50000.50"))
        self.assertEqual(result.amount, Decimal("55001.00"))
        self.assertEqual(result.transaction_fee, Decimal("5000.50"))

    def test_channel_without_rate_is_unavailable(self):
        no_rate = Channel("CC", "Kartu Kredit", PaymentMethod.CREDIT_CARD, FeeType.PERCENT, None)
        with self.assertRaises(ChannelNotAvailable):
            fees.calculate_transaction_fee(no_rate, Decimal("50000"))

    def test_inactive_channel_is_unavailable(self):
        inactive = Channel("VABCA", "x", PaymentMethod.VIRTUAL_ACCOUNT, FeeType.FLAT, Decimal("5000"), is_active=False)
        with self.assertRaises(ChannelNotAvailable):
            fees.calculate_transaction_fee(inactive, Decimal("50000"))

    def test_limits_apply_to_amount_after_fee(self):
        with self.assertRaises(ChannelNotAvailable):
            fees.calculate_transaction_fee(CC, Decimal("9000"))
        # 98,500,000 grossed up = 100,510,205 > 100,000,000
        with self.assertRaises(ChannelNotAvailable):
            fees.calculate_transaction_fee(CC, Decimal("98500000"))
        # VA min 10,000 is met by 5,000 + 5,000 fee
        self.assertEqual(fees.calculate_transaction_fee(VA, Decimal("5000")).amount, Decimal("10000.00"))

    def test_invalid_invoice_total(self):
        with self.assertRaises(InvalidAmount):
            fees.calculate_transaction_fee(VA, Decimal("0"))
        with self.assertRaises(InvalidAmount):
            fees.calculate_transaction_fee(VA, "abc")

    def test_invalid_percentage_rate(self):
        bad = Channel("CC", "x", PaymentMethod.CREDIT_CARD, FeeType.PERCENT, Decimal("100"))
        with self.assertRaises(ChannelNotAvailable):
            fees.calculate_transaction_fee(bad, Decimal("50000"))

    def test_available_channels_skips_out_of_range(self):
        codes = [b.channel_code for b in fees.available_channels([VA, CC], Decimal("99000000"))]
        self.assertEqual(codes, ["VABCA"])


class WithdrawalTests(SimpleTestCase):
    def test_fee_deducted_from_amount(self):
        result = fees.calculate_withdrawal(RULES, Decimal("1500000"))
        self.assertEqual(result.amount, Decimal("1500000.00"))
        self.assertEqual(result.fee, Decimal("2500.00"))
        self.assertEqual(result.transfer_amount, Decimal("1497500.00"))

    def test_amount_must_exceed_fee(self):
        self.assertEqual(
            fees.calculate_withdrawal(RULES, Decimal("2501")).transfer_amount,
            Decimal("1.00"),
        )
        for value in ("2500", "1000"):
            with self.assertRaises(AmountBelowMinimum, msg=value):
                fees.calculate_withdrawal(RULES, Decimal(value))

    def test_no_maximum(self):
        self.assertEqual(
            fees.calculate_withdrawal(RULES, Decimal("1000000000")).transfer_amount,
            Decimal("999997500.00"),
        )

    def test_amount_must_be_positive_whole_rupiah(self):
        for value in ("0", "-1", "50000.50", "abc"):
            with self.assertRaises(InvalidAmount, msg=value):
                fees.calculate_withdrawal(RULES, value)
