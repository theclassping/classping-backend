"""End to end through the real Rintisan provider (HTTP faked, signatures real):
paid callback -> settlement -> withdrawal with OTP -> disbursement callback.
The wallet must match the ledger at the end."""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.payment_aggregator.aggregator import set_provider
from payment_aggregator.providers.rintisan import signing
from apps.payment_aggregator.testing import CLIENT_ID, FakeResponse, key_pair, make_provider
from apps.payment_gateway import services as gateway_services
from apps.payment_gateway.test_payment_flow import EMAIL_TASK, PaymentFlowMixin, callback_body

from . import services
from .models import BranchWallet, LedgerEntry, Withdrawal
from .tests import MAILER, TEMPLATES


def rintisan_headers(raw):
    return {
        "HTTP_X_CALLBACK_TOKEN": "callback-token",
        "HTTP_X_SIGNATURE": signing.sign(CLIENT_ID, raw, key_pair("rintisan")[0]),
    }


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

        # 2. Rintisan settles it.
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
            FakeResponse(body={
                "response_code": "200", "disbursement_id": "DISPTR-1",
                "amount_request": 100000, "disburse_fee": 2500, "disburse_amount": 97500,
            })
        )
        set_provider(provider)
        with mock.patch(MAILER):
            created = staff.post(
                "/api/withdrawals/",
                {"otp_reference": preview.data["otp_reference"], "otp": code, "fee_acknowledged": True},
                format="json",
            )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(session.last_json()["amount"], 100000)  # full amount; Rintisan deducts its fee

        # 4. Rintisan reports the disbursement as successful.
        raw = signing.minify({
            "timestamp": "2026-11-08 10:35:12", "disbursement_id": "DISPTR-1",
            "partner_reference_id": created.data["withdrawal_no"], "amount_request": 100000,
            "disburse_fee": 2500, "disburse_amount": 97500, "bank_code": "BCA",
            "account_number": "5271234567", "status": {"code": "200", "message": "success"},
        }).encode()
        with mock.patch(MAILER):
            response = self.client.post(
                "/api/webhooks/rintisan/disbursement/", raw, content_type="application/json", **rintisan_headers(raw)
            )
        self.assertEqual(response.json(), {"status": "ok"})

        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.SUCCESS)
        self.assertFalse(withdrawal.needs_review)
        wallet.refresh_from_db()
        self.assertEqual((wallet.available_balance, wallet.pending_balance), (Decimal("25000"), Decimal("0")))
        self.assertEqual(LedgerEntry.objects.order_by("-pk").first().balance_after, Decimal("25000"))
        self.assertEqual(services.check_branch_balances(), [])

        summary = staff.get("/api/wallet/").data
        self.assertEqual((summary["withdrawn_total"], summary["withdrawn_count"]), ("100000.00", 1))
