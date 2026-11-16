"""End to end through the real DANA provider (HTTP faked, signatures real):
paid callback -> settlement -> withdrawal with OTP -> disbursement callback.
The wallet must match the ledger at the end."""

import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.payment_aggregator.aggregator import set_provider
from apps.payment_aggregator.testing import FakeResponse, dana_notify_headers, make_provider
from apps.payment_gateway import services as gateway_services
from apps.payment_gateway.test_payment_flow import EMAIL_TASK, PaymentFlowMixin, callback_body

from . import services
from .models import BranchWallet, LedgerEntry, Withdrawal
from .tests import MAILER, TEMPLATES


def dana_headers(path, raw):
    return {"HTTP_" + k.upper().replace("-", "_"): v for k, v in dana_notify_headers(path, raw).items()}


@override_settings(MAILJET_TEMPLATES=TEMPLATES)
class PaymentToWithdrawalFlowTests(PaymentFlowMixin, TestCase):
    def test_paid_settled_withdrawn(self):
        self.branch.email = "admin@sekolah.sch.id"
        self.branch.save(update_fields=["email"])

        # 1. Parent pays the checkout (2 invoices, 125.000 + 5.000 VA fee).
        with mock.patch(EMAIL_TASK):
            self.assertEqual(self.post_callback(callback_body()).status_code, 200)
        wallet = BranchWallet.objects.get(branch=self.branch)
        self.assertEqual((wallet.available_balance, wallet.pending_balance), (Decimal("0"), Decimal("125000")))

        # 2. DANA settles it.
        gateway_services.mark_gateway_payment_settled(self.checkout_row.pk)

        # 3. The officer withdraws 100.000 with the OTP emailed to the branch.
        staff = APIClient()
        staff.force_authenticate(user=self.staff_user)
        with mock.patch(MAILER) as mailer:
            preview = staff.post(
                "/api/withdrawals/preview/",
                {"amount": "100000", "bank_code": "BCA", "account_number": "5271234567", "account_holder_name": "YAYASAN"},
                format="json",
            )
        self.assertEqual(preview.status_code, 200, preview.data)
        code = mailer.return_value.send_template.call_args.kwargs["variables"]["otp"]

        provider, session = make_provider(
            # Bank account inquiry, Transfer to Bank (in progress), then the
            # status inquiry the notification triggers (00 = success).
            FakeResponse(body={
                "responseCode": "2004200", "responseMessage": "Successful",
                "beneficiaryAccountName": "YAYASAN",
                "additionalInfo": {"feeAmount": {"value": "2500.00", "currency": "IDR"}},
            }),
            FakeResponse(body={"responseCode": "2024300", "responseMessage": "Request In Progress"}),
            FakeResponse(body={
                "responseCode": "2000000", "responseMessage": "Successful", "latestTransactionStatus": "00",
                "amount": {"value": "97500.00", "currency": "IDR"},
            }),
        )
        set_provider(provider)
        with mock.patch(MAILER):
            created = staff.post(
                "/api/withdrawals/",
                {"otp_reference": preview.data["otp_reference"], "otp": code, "fee_acknowledged": True},
                format="json",
            )
        self.assertEqual(created.status_code, 201, created.data)
        # The bank account receives the amount minus the Rp2.500 fee.
        self.assertEqual(session.last_json()["amount"], {"value": "97500.00", "currency": "IDR"})

        # 4. DANA notifies; the status inquiry confirms the transfer succeeded.
        url = "/api/webhooks/disbursement/"  # provider-neutral: sender found by signature
        raw = json.dumps({
            "originalPartnerReferenceNo": created.data["withdrawal_no"], "latestTransactionStatus": "00",
        }).encode()
        with mock.patch(MAILER):
            response = self.client.post(url, raw, content_type="application/json", **dana_headers(url, raw))
        self.assertEqual(response.json()["responseCode"], "2004300")

        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.SUCCESS)
        self.assertFalse(withdrawal.needs_review)
        wallet.refresh_from_db()
        self.assertEqual((wallet.available_balance, wallet.pending_balance), (Decimal("25000"), Decimal("0")))
        self.assertEqual(LedgerEntry.objects.order_by("-pk").first().balance_after, Decimal("25000"))
        self.assertEqual(services.check_branch_balances(), [])

        summary = staff.get("/api/wallet/").data
        self.assertEqual((summary["withdrawn_total"], summary["withdrawn_count"]), ("100000.00", 1))
