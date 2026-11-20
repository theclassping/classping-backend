"""Settlement from DANA's settlement file (preview, import, admin web, command),
with ClassPing checkouts: SPP 125.000 + VA BRI fee 2.775 = 127.775 per checkout."""

import datetime
import os
import tempfile
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.payment_aggregator.aggregator import set_provider
from apps.payment_aggregator.testing import make_provider
from apps.users.models import User
from apps.wallets import services as wallet_services
from apps.wallets.models import BranchWallet

from . import exceptions as errors
from . import services
from . import settlement
from .models import GatewayPayment, SettlementFile, SettlementLine
from .tests import GatewayFixtureMixin

HEADER = (
    "SETTLEMENT_TXN_ID;TXN_ID;TXN_TYPE;ACQUIREMENT_ID;MID;SETTLE_DATE;MERCHANT_NAME;TXN_AMOUNT;TXN_CURRENCY;"
    "TXN_DATE;ORIGINAL_TXN_ID;ORIGINAL_TXN_DATE;MERCHANT_COMMISSION_EDIK;SERVICE_TAX_EDIK;WITHHOLDING_TAX_EDIK;"
    "MERCHANT_COMMISSION_ASR;SERVICE_TAX_ASR;WITHHOLDING_TAX_ASR;SETTLE_AMOUNT;MERCHANT_TRANS_ID;"
    "MERCHANT_REQUEST_ID;PAY_METHOD;MERCHANT_CUST_ID;SETTLE_UNIT_TYPE;SETTLE_UNIT_VALUE;SHOP_ID;BUYER_MOBILE_NO;"
    "DIVISION_ID;PRODUCT_TYPE"
)
SETTLE_DATE = "2026-11-19T10:00:00+07:00"
MID = "216620000000000000000"
FILE_NAME = "MERCHANT_SETTLEMENT_216620000000000000000_MERCHANT_CLASSPING_20261118.csv"
# DANA referenceNo of each checkout (our provider_trx_id).
TRX_1 = "20261118111212800100166000000001"
TRX_2 = "20261118111212800100166000000002"
TRX_3 = "20261118111212800100166000000003"
TRX_4 = "20261118111212800100166000000004"
TRX_UNKNOWN = "20261118111212800100166000000099"
VA_FEE = Decimal("2775")
SPP = Decimal("125000")
CHECKOUT = SPP + VA_FEE  # 127.775
WIB = datetime.timezone(datetime.timedelta(hours=7))


def line(txn_id, amount=CHECKOUT, txn_type="ACQUIRING_ORDER", reference="", original="", pay_method="VIRTUAL_ACCOUNT"):
    """One settlement line; DANA writes amounts in cents."""
    cents = int(Decimal(amount) * 100)
    fee = int(VA_FEE * 100) if txn_type == "ACQUIRING_ORDER" else 0
    return ";".join(str(value) for value in [
        "20261119111213810400166000000001", txn_id, txn_type, "", MID, SETTLE_DATE, "ClassPing", cents, "IDR",
        "2026-11-18T09:00:00+07:00", original, "", fee, 0, 0, 0, 0, 0, cents - fee, reference, "", pay_method,
        "", "MERCHANT", "DEFAULT", "", "", "", "",
    ])


def csv_bytes(*lines):
    return "\n".join((HEADER,) + lines).encode("utf-8")


class SettlementFixtureMixin(GatewayFixtureMixin):
    def setUp(self):
        super().setUp()
        set_provider(make_provider()[0])
        self.addCleanup(set_provider, None)
        self.paid = self.paid_checkout("PAY-20261118-000001", TRX_1)
        self.paid_2 = self.paid_checkout("PAY-20261118-000002", TRX_2)

    def paid_checkout(self, payment_no, provider_trx_id, **overrides):
        values = dict(
            status=GatewayPayment.Status.PAID, provider_trx_id=provider_trx_id, channel_code="VIRTUAL_ACCOUNT_BRI",
            invoice_total=SPP, transaction_fee=VA_FEE, amount=CHECKOUT,
        )
        values.update(overrides)
        checkout = self.make_payment(payment_no, "key-" + payment_no, **values)
        with transaction.atomic():
            wallet_services.post_payment_credit(checkout)
        return checkout

    def wallet(self):
        return BranchWallet.objects.get(branch=self.branch)


class SettlementImportTests(SettlementFixtureMixin, TestCase):
    def test_preview_changes_nothing(self):
        preview = settlement.preview_settlement_file("dana", FILE_NAME, csv_bytes(line(TRX_1)))
        self.assertEqual(preview.settled_count, 1)
        self.assertEqual(preview.settled_total, CHECKOUT)
        self.paid.refresh_from_db()
        self.assertIsNone(self.paid.settled_at)
        self.assertFalse(SettlementFile.objects.exists())
        self.assertEqual(self.wallet().available_balance, Decimal("0"))

    def test_import_settles_matching_paid_payments(self):
        imported = settlement.import_settlement_file(
            None, "dana", FILE_NAME,
            csv_bytes(line(TRX_1), line(TRX_2)),
        )
        self.assertEqual((imported.line_count, imported.settled_count, imported.review_count), (2, 2, 0))
        self.assertEqual(imported.settle_amount_total, Decimal("250000.00"))  # 2 x (127.775 - 2.775 DANA fee)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.settled_at, datetime.datetime(2026, 11, 19, 10, 0, tzinfo=WIB))
        wallet = self.wallet()
        self.assertEqual((wallet.available_balance, wallet.pending_balance), (Decimal("250000"), Decimal("0")))
        row = imported.lines.get(line_no=1)
        self.assertEqual((row.result, row.gateway_payment, row.fee), (SettlementLine.Result.SETTLED, self.paid,
                                                                       Decimal("2775.00")))

    def test_falls_back_to_our_reference(self):
        imported = settlement.import_settlement_file(
            None, "dana", FILE_NAME, csv_bytes(line(TRX_UNKNOWN, reference="PAY-20261118-000001"))
        )
        self.assertEqual(imported.lines.get().gateway_payment, self.paid)
        self.assertEqual(imported.settled_count, 1)

    def test_mismatches_are_flagged_not_settled(self):
        pending = self.make_payment(
            "PAY-20261118-000003", "key-3", provider_trx_id=TRX_3, channel_code="VIRTUAL_ACCOUNT_BRI",
            invoice_total=SPP, transaction_fee=VA_FEE, amount=CHECKOUT,
        )
        imported = settlement.import_settlement_file(None, "dana", FILE_NAME, csv_bytes(
            line(TRX_1, "127000"),  # amount differs
            line(TRX_3),  # not paid in Classping
            line(TRX_UNKNOWN, "50000"),  # unknown
            line(TRX_2, txn_type="CAPTURE"),  # not used by Classping
        ))
        results = list(imported.lines.values_list("result", flat=True))
        self.assertEqual(results, ["amount_mismatch", "not_paid", "unmatched", "ignored"])
        self.assertEqual((imported.settled_count, imported.review_count, imported.unmatched_count), (0, 2, 1))
        self.paid.refresh_from_db()
        pending.refresh_from_db()
        self.assertIsNone(self.paid.settled_at)
        self.assertTrue(self.paid.needs_review)
        self.assertIn("File amount 127000.00, Classping amount 127775.00", self.paid.review_note)
        self.assertTrue(pending.needs_review)
        self.assertEqual(self.wallet().available_balance, Decimal("0"))

    def test_already_settled_and_duplicate_lines(self):
        services.mark_gateway_payment_settled(self.paid.pk)
        imported = settlement.import_settlement_file(None, "dana", FILE_NAME, csv_bytes(
            line(TRX_1), line(TRX_2), line(TRX_2),
        ))
        results = list(imported.lines.values_list("result", flat=True))
        self.assertEqual(results, ["already_settled", "settled", "already_settled"])
        self.assertEqual(self.wallet().available_balance, Decimal("250000"))  # each credit moved once

    def test_refund_cancel_and_adjustment_lines(self):
        refunded = self.paid_checkout(
            "PAY-20261118-000004", TRX_4, refund_status=GatewayPayment.RefundStatus.REFUNDED, refund_amount=CHECKOUT,
        )
        imported = settlement.import_settlement_file(None, "dana", FILE_NAME, csv_bytes(
            line("20261118111212801300166000000011", txn_type="REFUND", original=TRX_4),  # matches our refund
            line("20261118111212801300166000000012", txn_type="REFUND", original=TRX_1),  # we never refunded
            line("20261118111212800110166000000013", txn_type="CANCEL", original=TRX_2),  # paid in Classping
            line(TRX_2, pay_method="ADJUSTMENT"),  # DANA credit: refund failed
        ))
        results = list(imported.lines.values_list("result", flat=True))
        self.assertEqual(results, ["checked", "review", "review", "review"])
        refunded.refresh_from_db()
        self.paid.refresh_from_db()
        self.paid_2.refresh_from_db()
        self.assertFalse(refunded.needs_review)
        self.assertTrue(self.paid.needs_review)
        self.assertTrue(self.paid_2.needs_review)
        self.assertIsNone(self.paid_2.settled_at)  # an ADJUSTMENT never settles

    def test_same_file_twice_is_refused(self):
        content = csv_bytes(line(TRX_1))
        settlement.import_settlement_file(None, "dana", FILE_NAME, content)
        with self.assertRaises(errors.SettlementFileAlreadyImported):
            settlement.preview_settlement_file("dana", "MERCHANT_SETTLEMENT_COPY.csv", content)
        with self.assertRaises(errors.SettlementFileAlreadyImported):
            settlement.import_settlement_file(None, "dana", "MERCHANT_SETTLEMENT_COPY.csv", content)

    def test_invalid_file(self):
        with self.assertRaisesRegex(errors.SettlementFileInvalid, "missing column"):
            settlement.preview_settlement_file("dana", FILE_NAME, b"a,b\n1,2\n")
        self.assertFalse(SettlementFile.objects.exists())

    def test_hourly_reconcile_no_longer_polls_dana(self):
        with mock.patch("payment_aggregator.providers.dana.provider.DanaProvider.get_billing_status") as status:
            self.assertEqual(services.reconcile_settlements(), 0)
        status.assert_not_called()


class SettlementAdminWebTests(SettlementFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            email="settle-file-admin@example.com", password="StrongPassword123!", first_name="S", last_name="A",
        )
        self.client.force_login(self.admin)

    def upload(self, content, name=FILE_NAME):
        return self.client.post(
            reverse("admin_web:settlement_list"), {"file": SimpleUploadedFile(name, content, "text/csv")}
        )

    def test_upload_preview_then_import(self):
        response = self.upload(csv_bytes(line(TRX_1), line(TRX_UNKNOWN, "50000")))
        self.assertRedirects(response, reverse("admin_web:settlement_preview"), fetch_redirect_response=False)
        preview = self.client.get(reverse("admin_web:settlement_preview"))
        self.assertContains(preview, "Will be settled")
        self.assertContains(preview, "PAY-20261118-000001")
        self.assertContains(preview, "No matching payment")
        self.paid.refresh_from_db()
        self.assertIsNone(self.paid.settled_at)  # preview changes nothing

        response = self.client.post(reverse("admin_web:settlement_preview"), {"action": "import"})
        imported = SettlementFile.objects.get()
        self.assertRedirects(
            response, reverse("admin_web:settlement_detail", args=[imported.pk]), fetch_redirect_response=False
        )
        self.assertEqual(imported.imported_by, self.admin)
        self.paid.refresh_from_db()
        self.assertIsNotNone(self.paid.settled_at)
        detail = self.client.get(reverse("admin_web:settlement_detail", args=[imported.pk]), {"result": "unmatched"})
        self.assertContains(detail, TRX_UNKNOWN)
        self.assertNotContains(detail, TRX_1)
        self.assertContains(self.client.get(reverse("admin_web:settlement_list")), imported.file_name)

    def test_cancel_preview(self):
        self.upload(csv_bytes(line(TRX_1)))
        self.client.post(reverse("admin_web:settlement_preview"), {"action": "cancel"})
        self.assertFalse(SettlementFile.objects.exists())
        self.assertRedirects(
            self.client.get(reverse("admin_web:settlement_preview")), reverse("admin_web:settlement_list"),
            fetch_redirect_response=False,
        )

    def test_upload_errors_stay_on_the_form(self):
        self.assertContains(self.upload(b"a,b\n1,2\n"), "missing column")
        self.assertContains(self.upload(csv_bytes(), name="settlement.xlsx"), "Upload the .csv settlement file.")
        content = csv_bytes(line(TRX_1))
        settlement.import_settlement_file(None, "dana", FILE_NAME, content)
        self.assertContains(self.upload(content), "already been imported")

    def test_online_payments_settlement_column_and_filter(self):
        services.mark_gateway_payment_settled(self.paid.pk)
        unpaid = self.make_payment("PAY-20261118-000005", "key-5")
        url = reverse("admin_web:gateway_payment_list")

        listing = self.client.get(url)
        self.assertContains(listing, "<th>Settlement</th>", html=False)
        self.assertContains(listing, "Pending settlement")

        def shown(settlement):
            page = self.client.get(url, {"settlement": settlement}).context["page_obj"]
            return {payment.payment_no for payment in page}

        self.assertEqual(shown("settled"), {self.paid.payment_no})
        self.assertEqual(shown("pending"), {self.paid_2.payment_no})  # paid, not settled
        self.assertEqual(shown(""), {self.paid.payment_no, self.paid_2.payment_no, unpaid.payment_no})

    def test_platform_admin_only(self):
        self.client.force_login(self.staff_user)
        self.upload(csv_bytes(line(TRX_1)))
        self.assertNotEqual(self.client.get(reverse("admin_web:settlement_list")).status_code, 200)
        self.paid.refresh_from_db()
        self.assertIsNone(self.paid.settled_at)


class ImportDanaSettlementCommandTests(SettlementFixtureMixin, TestCase):
    def write(self, content):
        handle = tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False)
        handle.write(content)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_dry_run_then_import(self):
        path = self.write(csv_bytes(line(TRX_1)))
        out = StringIO()
        call_command("import_dana_settlement", path, "--dry-run", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertFalse(SettlementFile.objects.exists())
        call_command("import_dana_settlement", path, stdout=StringIO())
        self.paid.refresh_from_db()
        self.assertIsNotNone(self.paid.settled_at)
        with self.assertRaisesRegex(CommandError, "already been imported"):
            call_command("import_dana_settlement", path, stdout=StringIO())
