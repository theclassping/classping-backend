"""DANA settlement file parsing, with ClassPing transactions (school invoices
paid through Gapura Custom Checkout; column layout from DANA's spec v1.2.0)."""

import datetime
import unittest
from decimal import Decimal

from payment_aggregator import PaymentAggregator
from payment_aggregator.base import SettlementLineType
from payment_aggregator.exceptions import InvalidSettlementFile
from payment_aggregator.testing import make_dana_provider

HEADER = (
    "SETTLEMENT_TXN_ID;TXN_ID;TXN_TYPE;ACQUIREMENT_ID;MID;SETTLE_DATE;MERCHANT_NAME;TXN_AMOUNT;TXN_CURRENCY;"
    "TXN_DATE;ORIGINAL_TXN_ID;ORIGINAL_TXN_DATE;MERCHANT_COMMISSION_EDIK;SERVICE_TAX_EDIK;WITHHOLDING_TAX_EDIK;"
    "MERCHANT_COMMISSION_ASR;SERVICE_TAX_ASR;WITHHOLDING_TAX_ASR;SETTLE_AMOUNT;MERCHANT_TRANS_ID;"
    "MERCHANT_REQUEST_ID;PAY_METHOD;MERCHANT_CUST_ID;SETTLE_UNIT_TYPE;SETTLE_UNIT_VALUE;SHOP_ID;BUYER_MOBILE_NO;"
    "DIVISION_ID;PRODUCT_TYPE"
)
MID = "216620000000000000000"
BATCH = "20261119111213810400166000000001"
SETTLE_DATE = "2026-11-19T00:00:21+07:00"

# ClassPing checkouts (payment_no is our partnerReferenceNo, the DANA id its referenceNo).
VA_PAYMENT = ("PAY-20261118-000001", "20261118111212800100166000000001")  # SPP 125.000 + VA fee 2.775
CARD_PAYMENT = ("PAY-20261118-000002", "20261118111212800100166000000002")  # Outing 75.000 + card fee


def row(txn_id, txn_type, amount, *, acquirement_id="", original_txn_id="", commission=0, tax=0,
        reference="", request_id="", pay_method="VIRTUAL_ACCOUNT", settle_amount=None,
        settle_date=SETTLE_DATE, txn_date="2026-11-18T09:15:00+07:00"):
    """One settlement line; amounts in rupiah, written in cents as DANA does."""
    cents = int(Decimal(amount) * 100)
    commission_cents, tax_cents = int(Decimal(commission) * 100), int(Decimal(tax) * 100)
    if settle_amount is None:
        settle_cents = cents - commission_cents - tax_cents
    else:
        settle_cents = int(Decimal(settle_amount) * 100)
    original_date = "2026-11-18T09:15:00+07:00" if original_txn_id else ""
    return ";".join(str(value) for value in [
        BATCH, txn_id, txn_type, acquirement_id, MID, settle_date, "ClassPing", cents, "IDR", txn_date,
        original_txn_id, original_date, commission_cents, tax_cents, 0, 0, 0, 0, settle_cents, reference,
        request_id, pay_method, "", "MERCHANT", "DEFAULT", "", "", "", "",
    ])


# A day of ClassPing transactions.
DAY = "\n".join([
    HEADER,
    # Parent pays SPP by VA BRI; ACQUIREMENT_ID left empty (DANA's sample does this too).
    row(VA_PAYMENT[1], "ACQUIRING_ORDER", "127775", commission="2500", tax="275", reference=VA_PAYMENT[0]),
    # Admin refunded the card payment of an outing that was cancelled by the school.
    row("20261118111212801300166000000003", "REFUND", "77189", original_txn_id=CARD_PAYMENT[1],
        reference=CARD_PAYMENT[0], request_id="RF-" + CARD_PAYMENT[0], pay_method="NETWORK_PAY", settle_amount="0"),
    # Checkout cancelled by DANA after payment.
    row(CARD_PAYMENT[1], "CANCEL", "77189", original_txn_id=CARD_PAYMENT[1], reference=CARD_PAYMENT[0],
        pay_method="NETWORK_PAY", settle_amount="0"),
    # A line type ClassPing does not use.
    row("20261118111212801800166000000004", "CAPTURE", "50000", acquirement_id="20261118111212800100166000000004",
        reference="PAY-20261118-000004"),
    # DANA could not refund the payer and credited ClassPing instead.
    row(CARD_PAYMENT[1], "ACQUIRING_ORDER", "77189", acquirement_id=CARD_PAYMENT[1], reference=CARD_PAYMENT[0],
        pay_method="ADJUSTMENT"),
    "",
])

WIB = datetime.timezone(datetime.timedelta(hours=7))


class DanaSettlementFileTests(unittest.TestCase):
    def setUp(self):
        provider, _ = make_dana_provider()
        self.aggregator = PaymentAggregator(provider)

    def test_settlement_comes_from_the_file(self):
        self.assertTrue(self.aggregator.settlement_via_file())

    def test_parses_a_day_of_classping_transactions(self):
        lines = self.aggregator.parse_settlement_file(DAY)
        self.assertEqual(
            [line.type for line in lines],
            [
                SettlementLineType.PAYMENT,
                SettlementLineType.REFUND,
                SettlementLineType.CANCEL,
                SettlementLineType.OTHER,
                SettlementLineType.ADJUSTMENT,
            ],
        )
        payment = lines[0]
        self.assertEqual(payment.line_no, 1)
        self.assertEqual(payment.provider_type, "ACQUIRING_ORDER")
        # ACQUIREMENT_ID is empty: the checkout's DANA id comes from TXN_ID.
        self.assertEqual(payment.provider_trx_id, VA_PAYMENT[1])
        self.assertEqual(payment.reference_no, VA_PAYMENT[0])
        self.assertEqual(payment.amount, Decimal("127775.00"))  # cents -> rupiah
        self.assertEqual(payment.fee, Decimal("2775.00"))  # commission + its tax
        self.assertEqual(payment.settle_amount, Decimal("125000.00"))
        self.assertEqual(payment.settled_at, datetime.datetime(2026, 11, 19, 0, 0, 21, tzinfo=WIB))
        self.assertEqual(payment.transaction_at, datetime.datetime(2026, 11, 18, 9, 15, tzinfo=WIB))
        self.assertEqual(payment.batch_no, BATCH)
        self.assertEqual(payment.raw["MERCHANT_NAME"], "ClassPing")

        refund = lines[1]
        self.assertEqual(refund.original_trx_id, CARD_PAYMENT[1])
        self.assertEqual(refund.reference_no, CARD_PAYMENT[0])
        self.assertEqual(refund.amount, Decimal("77189.00"))
        self.assertEqual(refund.raw["MERCHANT_REQUEST_ID"], "RF-PAY-20261118-000002")

        adjustment = lines[4]
        self.assertEqual(adjustment.provider_type, "ACQUIRING_ORDER")
        self.assertEqual(adjustment.pay_method, "ADJUSTMENT")

    def test_bytes_with_bom_and_crlf(self):
        lines = self.aggregator.parse_settlement_file(("﻿" + DAY.replace("\n", "\r\n")).encode("utf-8"))
        self.assertEqual(len(lines), 5)

    def test_header_only(self):
        self.assertEqual(self.aggregator.parse_settlement_file(HEADER + "\n"), [])

    def test_rejects_other_formats(self):
        for content in ("a,b,c\n1,2,3\n", "", HEADER.replace(";", ",") + "\n"):
            with self.subTest(content=content[:20]):
                with self.assertRaises(InvalidSettlementFile):
                    self.aggregator.parse_settlement_file(content)

    def test_rejects_bad_values_with_line_number(self):
        payment = DAY.split("\n")[1]
        bad_amount = payment.replace(";12777500;IDR;", ";127.775,00;IDR;", 1)
        with self.assertRaisesRegex(InvalidSettlementFile, "Line 1: TXN_AMOUNT"):
            self.aggregator.parse_settlement_file("\n".join([HEADER, bad_amount]))
        bad_date = payment.replace(SETTLE_DATE, "19/11/2026", 1)
        with self.assertRaisesRegex(InvalidSettlementFile, "Line 1: SETTLE_DATE"):
            self.aggregator.parse_settlement_file("\n".join([HEADER, bad_date]))
        with self.assertRaises(InvalidSettlementFile):
            self.aggregator.parse_settlement_file(b"\xff\xfe\x00bad")
