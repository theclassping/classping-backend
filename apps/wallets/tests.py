import datetime
import threading
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.locations.models import Location
from payment_aggregator import exceptions as provider_errors
from payment_aggregator.base import TransferResult, TransferStatus
from apps.payment_gateway.tests import PASSWORD, NoMailjetMixin, make_branch, make_parent, make_staff
from apps.schools.models import School
from apps.staffs.models import Staff
from apps.users.models import User

from . import services
from .models import BranchWallet, LedgerEntry, PayoutAccount, Withdrawal, WithdrawalOtp

TEMPLATES = {
    "invoice_reminder": 1, "payment_submitted": 2, "payment_completed": 3, "payment_rejected": 4,
    "welcome_email": 5, "withdrawal_otp": 101, "withdrawal_status": 102,
}
MAILER = "apps.wallets.services.Mailer"
TRANSFER = "apps.wallets.services.PaymentAggregator.transfer_balance"
NEW_ACCOUNT = {"bank_code": "BCA", "account_number": "5271234567", "account_holder_name": "YAYASAN PENDIDIKAN"}


def accepted(reference_no="", **overrides):
    values = dict(
        reference_no=reference_no,
        provider_transfer_id="DISPTR-1",
        status=TransferStatus.PROCESSING,
        amount_requested=Decimal("100000"),
        fee=Decimal("2500"),
        amount_received=Decimal("97500"),
        raw={"response_code": "200"},
    )
    values.update(overrides)
    return TransferResult(**values)


class WalletFixtureMixin:
    def setUp(self):
        location = Location.objects.create(name="WL Province", code="WLP", location_type="PROVINCE")
        school = School.objects.create(name="WL School", register_number="WL-001")
        self.branch = make_branch(school, location, "WL-A")
        self.branch.email = "admin@sekolah.sch.id"
        self.branch.save(update_fields=["email"])
        self.other_branch = make_branch(school, location, "WL-B")
        self.officer = make_staff(self.branch, "wl-officer@example.com", Staff.StaffType.OFFICER)
        self.principal = make_staff(self.branch, "wl-principal@example.com", Staff.StaffType.PRINCIPAL)
        self.teacher = make_staff(self.branch, "wl-teacher@example.com", Staff.StaffType.TEACHER, role=User.Role.TEACHER)
        self.teacher_staff_role = make_staff(self.branch, "wl-teacher2@example.com", Staff.StaffType.TEACHER)
        self.other_officer = make_staff(self.other_branch, "wl-officer-b@example.com", Staff.StaffType.OFFICER)
        self.parent, _ = make_parent("wl-parent@example.com", "Parent")
        BranchWallet.objects.create(branch=self.branch, available_balance=Decimal("150000"))
        # Active provider: DANA with Classping's rates (no HTTP unless a test queues responses).
        from apps.payment_aggregator.aggregator import set_provider
        from apps.payment_aggregator.testing import make_provider

        set_provider(make_provider()[0])
        self.addCleanup(set_provider, None)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def wallet(self):
        return BranchWallet.objects.get(branch=self.branch)


@override_settings(MAILJET_TEMPLATES=TEMPLATES)
class WithdrawalApiTests(WalletFixtureMixin, TestCase):
    def preview(self, user=None, amount="100000", **destination):
        payload = {"amount": amount, **(destination or NEW_ACCOUNT)}
        with mock.patch(MAILER) as mailer:
            response = self.client_for(user or self.officer).post("/api/withdrawals/preview/", payload, format="json")
        code = None
        if mailer.return_value.send_template.called:
            code = mailer.return_value.send_template.call_args.kwargs["variables"]["otp"]
        return response, code

    def submit(self, reference, code, user=None, result=None, side_effect=None, fee_acknowledged=True):
        with mock.patch(TRANSFER, return_value=result or accepted(), side_effect=side_effect) as transfer, \
                mock.patch(MAILER) as mailer:
            response = self.client_for(user or self.officer).post(
                "/api/withdrawals/",
                {"otp_reference": reference, "otp": code, "fee_acknowledged": fee_acknowledged},
                format="json",
            )
        self.last_transfer, self.last_mailer = transfer, mailer
        return response

    # --- access ---------------------------------------------------------

    def test_only_branch_principal_and_officer(self):
        for user in (self.officer, self.principal):
            response = self.client_for(user).get("/api/wallet/")
            self.assertEqual(response.status_code, 200, user.email)
            self.assertEqual(response.data["available_balance"], "150000.00")
            self.assertEqual(response.data["withdrawal_fee"], "2500.00")
        for user in (self.teacher, self.teacher_staff_role, self.parent):
            self.assertEqual(self.client_for(user).get("/api/wallet/").status_code, 403, user.email)
            self.assertEqual(self.client_for(user).post("/api/withdrawals/preview/", {}).status_code, 403, user.email)

    def test_other_branch_sees_its_own_wallet(self):
        response = self.client_for(self.other_officer).get("/api/wallet/")
        self.assertEqual(response.data["branch_id"], self.other_branch.pk)
        self.assertEqual(response.data["available_balance"], "0.00")

    # --- preview & OTP --------------------------------------------------

    def test_preview_sends_otp_to_branch_email(self):
        with mock.patch(MAILER) as mailer:
            response = self.client_for(self.officer).post(
                "/api/withdrawals/preview/", {"amount": "100000", **NEW_ACCOUNT}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["amount"], "100000.00")
        self.assertEqual(response.data["fee"], "2500.00")
        self.assertEqual(response.data["transfer_amount"], "97500.00")
        self.assertEqual(response.data["otp_sent_to"], "admin@sekolah.sch.id")
        self.assertEqual(response.data["payout_account"]["account_number_masked"], "****4567")
        kwargs = mailer.return_value.send_template.call_args.kwargs
        self.assertEqual(kwargs["to_email"], "admin@sekolah.sch.id")
        self.assertEqual(kwargs["template_id"], 101)
        self.assertEqual(set(kwargs["variables"]), {"name", "otp", "expires_in"})
        self.assertEqual(kwargs["variables"]["expires_in"], 3)
        self.assertRegex(kwargs["variables"]["otp"], r"^[0-9]{6}$")
        otp = WithdrawalOtp.objects.get(reference=response.data["otp_reference"])
        self.assertNotIn(kwargs["variables"]["otp"], otp.code_hash)
        # The account is saved only when a withdrawal is made.
        self.assertFalse(PayoutAccount.objects.exists())

    def test_preview_validation(self):
        cases = [
            ({"amount": "150001"}, "INSUFFICIENT_BALANCE"),
            ({"amount": "2500"}, "AMOUNT_BELOW_MINIMUM"),
            ({"amount": "50000.50"}, "INVALID_AMOUNT"),
            ({"amount": "100000", "bank_code": "GOPAY", "account_number": "0812345678", "account_holder_name": "X"},
             "PAYOUT_BANK_NOT_SUPPORTED"),
            ({"amount": "100000", "bank_code": "BCA"}, "PAYOUT_ACCOUNT_REQUIRED"),
        ]
        for payload, code in cases:
            payload = {**NEW_ACCOUNT, **payload} if "bank_code" not in payload else payload
            with mock.patch(MAILER):
                response = self.client_for(self.officer).post("/api/withdrawals/preview/", payload, format="json")
            self.assertEqual(response.status_code, 400, payload)
            self.assertEqual(response.data["code"], code, payload)
        self.assertFalse(WithdrawalOtp.objects.exists())

    def test_preview_without_branch_email(self):
        self.branch.email = ""
        self.branch.save(update_fields=["email"])
        response, _ = self.preview()
        self.assertEqual(response.data["code"], "BRANCH_EMAIL_MISSING")

    def test_preview_fails_when_otp_email_cannot_be_sent(self):
        with mock.patch(MAILER) as mailer:
            mailer.return_value.send_template.side_effect = Exception("Mailjet down")
            response = self.client_for(self.officer).post(
                "/api/withdrawals/preview/", {"amount": "100000", **NEW_ACCOUNT}, format="json"
            )
        self.assertEqual(response.data["code"], "OTP_NOT_SENT")
        self.assertFalse(WithdrawalOtp.objects.exists())

    # --- withdrawal -----------------------------------------------------

    def test_withdrawal_debits_balance_and_saves_account(self):
        preview, code = self.preview()
        response = self.submit(preview.data["otp_reference"], code)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "processing")
        self.assertRegex(response.data["withdrawal_no"], r"^WDR-\d{8}-\d{6}$")

        request = self.last_transfer.call_args.args[0]
        self.assertEqual(request.amount, Decimal("100000.00"))  # the provider deducts its fee
        self.assertEqual(request.reference_no, response.data["withdrawal_no"])
        self.assertEqual(request.account_name, "YAYASAN PENDIDIKAN")

        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.provider_disbursement_id, "DISPTR-1")
        self.assertFalse(withdrawal.needs_review)
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))
        self.assertEqual(
            sorted(withdrawal.ledger_entries.values_list("entry_type", "amount")),
            [("withdrawal", Decimal("-97500.00")), ("withdrawal_fee", Decimal("-2500.00"))],
        )
        account = PayoutAccount.objects.get()
        self.assertEqual((account.branch_id, account.created_by_id), (self.branch.pk, self.officer.pk))
        self.assertEqual(withdrawal.payout_account, account)

    def test_saved_account_is_listed_and_reused(self):
        preview, code = self.preview(amount="20000")
        self.submit(preview.data["otp_reference"], code)
        account = PayoutAccount.objects.get()

        listed = self.client_for(self.principal).get("/api/payout-accounts/")
        self.assertEqual([row["id"] for row in listed.data], [account.pk])
        self.assertEqual(listed.data[0]["account_number_masked"], "****4567")
        self.assertEqual(self.client_for(self.other_officer).get("/api/payout-accounts/").data, [])

        preview, code = self.preview(amount="20000", payout_account_id=account.pk)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.submit(preview.data["otp_reference"], code)
        self.assertEqual(PayoutAccount.objects.count(), 1)
        self.assertEqual(Withdrawal.objects.filter(payout_account=account).count(), 2)

        self.other_branch.email = "b@sekolah.sch.id"
        self.other_branch.save(update_fields=["email"])
        response, _ = self.preview(user=self.other_officer, payout_account_id=account.pk)
        self.assertEqual(response.data["code"], "PAYOUT_ACCOUNT_NOT_FOUND")

    def test_fee_must_be_acknowledged(self):
        preview, code = self.preview()
        response = self.submit(preview.data["otp_reference"], code, fee_acknowledged=False)
        self.assertEqual(response.data["code"], "FEE_NOT_ACKNOWLEDGED")
        self.assertFalse(Withdrawal.objects.exists())

    def test_wrong_otp_counted_until_max_attempts(self):
        preview, code = self.preview()
        wrong = "000000" if code != "000000" else "111111"
        first = self.submit(preview.data["otp_reference"], wrong)
        self.assertEqual(first.data["code"], "OTP_INVALID")
        self.assertEqual(first.data["remaining_attempts"], 2)
        self.submit(preview.data["otp_reference"], wrong)
        third = self.submit(preview.data["otp_reference"], wrong)
        self.assertEqual(third.data["code"], "OTP_MAX_ATTEMPTS")
        self.assertEqual(self.submit(preview.data["otp_reference"], code).data["code"], "OTP_MAX_ATTEMPTS")
        self.assertFalse(Withdrawal.objects.exists())
        self.last_transfer.assert_not_called()

    def test_expired_used_or_foreign_otp(self):
        preview, code = self.preview()
        reference = preview.data["otp_reference"]
        self.assertEqual(self.submit(reference, code, user=self.principal).data["code"], "OTP_EXPIRED")
        WithdrawalOtp.objects.filter(reference=reference).update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.submit(reference, code).data["code"], "OTP_EXPIRED")

        preview, code = self.preview()
        self.assertEqual(self.submit(preview.data["otp_reference"], code).status_code, 201)
        self.assertEqual(self.submit(preview.data["otp_reference"], code).data["code"], "OTP_EXPIRED")

    def test_resend_issues_a_new_otp(self):
        preview, old_code = self.preview()
        old_reference = preview.data["otp_reference"]
        with mock.patch(MAILER) as mailer:
            resent = self.client_for(self.officer).post("/api/withdrawals/otp/resend/", {"otp_reference": old_reference})
        self.assertEqual(resent.status_code, 200, resent.data)
        self.assertNotEqual(resent.data["otp_reference"], old_reference)
        self.assertEqual(resent.data["amount"], "100000.00")
        self.assertEqual(resent.data["payout_account"]["account_number_masked"], "****4567")
        new_code = mailer.return_value.send_template.call_args.kwargs["variables"]["otp"]
        self.assertEqual(self.submit(old_reference, old_code).data["code"], "OTP_EXPIRED")
        self.assertEqual(self.submit(resent.data["otp_reference"], new_code).status_code, 201)

    def test_balance_rechecked_at_submit(self):
        preview, code = self.preview()
        BranchWallet.objects.filter(branch=self.branch).update(available_balance=Decimal("99999"))
        response = self.submit(preview.data["otp_reference"], code)
        self.assertEqual(response.data["code"], "INSUFFICIENT_BALANCE")
        self.assertFalse(Withdrawal.objects.exists())
        # The OTP was not consumed by the failed attempt.
        self.assertIsNone(WithdrawalOtp.objects.get().used_at)

    def test_rejected_account_returns_the_balance(self):
        preview, code = self.preview()
        error = provider_errors.InvalidDestinationAccount("bad", provider_message="Invalid account number.")
        response = self.submit(preview.data["otp_reference"], code, side_effect=error)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "PAYOUT_ACCOUNT_INVALID")
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.FAILED)
        self.assertEqual(withdrawal.failure_reason, "Invalid account number.")
        self.assertEqual(self.wallet().available_balance, Decimal("150000"))
        self.assertEqual(withdrawal.ledger_entries.count(), 4)

    def test_provider_errors(self):
        cases = [
            (provider_errors.InsufficientProviderBalance("low"), 503, "PROVIDER_BALANCE_INSUFFICIENT"),
            (provider_errors.ProviderRejected("no"), 400, "WITHDRAWAL_REJECTED"),
            (provider_errors.ProviderAccessDenied("ip"), 503, "PROVIDER_UNAVAILABLE"),
        ]
        for error, status_code, code in cases:
            preview, otp_code = self.preview(amount="20000")
            with self.assertLogs("apps.wallets.services", "ERROR") if status_code == 503 else mock.MagicMock():
                response = self.submit(preview.data["otp_reference"], otp_code, side_effect=error)
            self.assertEqual((response.status_code, response.data["code"]), (status_code, code))
        self.assertEqual(self.wallet().available_balance, Decimal("150000"))
        self.assertEqual(Withdrawal.objects.filter(status=Withdrawal.Status.FAILED).count(), 3)

    def test_timeout_keeps_withdrawal_processing(self):
        preview, code = self.preview()
        with self.assertLogs("apps.wallets.services", "ERROR"):
            response = self.submit(preview.data["otp_reference"], code, side_effect=provider_errors.ProviderUnavailable("t"))
        self.assertEqual(response.status_code, 201)
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.PROCESSING)
        self.assertTrue(withdrawal.needs_review)
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))

    def test_history(self):
        preview, code = self.preview()
        self.submit(preview.data["otp_reference"], code)
        withdrawals = self.client_for(self.principal).get("/api/withdrawals/")
        self.assertEqual(len(withdrawals.data), 1)
        detail = self.client_for(self.officer).get(f"/api/withdrawals/{withdrawals.data[0]['id']}/")
        self.assertEqual(detail.data["transfer_amount"], "97500.00")
        self.assertEqual(self.client_for(self.other_officer).get(f"/api/withdrawals/{withdrawals.data[0]['id']}/").status_code, 404)
        ledger = self.client_for(self.officer).get("/api/wallet/ledger/")
        self.assertEqual({row["entry_type"] for row in ledger.data}, {"withdrawal", "withdrawal_fee"})


@override_settings(MAILJET_TEMPLATES=TEMPLATES)
class DisbursementResultTests(WalletFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        # These tests apply callbacks as is; the confirm-by-status path is
        # tested explicitly below (DANA itself confirms every callback).
        patcher = mock.patch(
            "apps.wallets.services.PaymentAggregator.confirm_transfer_callbacks", return_value=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        otp = WithdrawalOtp.objects.create(
            reference="ref-1", branch=self.branch, user=self.officer, amount=Decimal("100000"),
            code_hash="x", sent_to=self.branch.email, expires_at=timezone.now(), **NEW_ACCOUNT,
        )
        with mock.patch(TRANSFER, return_value=accepted()), mock.patch(MAILER):
            self.withdrawal = services._send_to_provider(
                services._create_processing_withdrawal(self.officer, otp, timezone.now())
            )

    def result(self, status, code, **overrides):
        return accepted(
            reference_no=self.withdrawal.withdrawal_no, status=status, provider_status_code=code,
            raw={"status": {"code": code}}, **overrides,
        )

    def post_callback(self, result):
        # Reply with the app's own status (DANA would always send its ACK).
        def reply(provider, event, default, result=None):
            return default

        with mock.patch("apps.wallets.services.PaymentAggregator.parse_transfer_callback", return_value=result), \
                mock.patch("apps.wallets.services.callback_reply", side_effect=reply), \
                mock.patch(MAILER) as mailer:
            response = APIClient().post("/api/webhooks/dana/disbursement/", b"{}", content_type="application/json")
        self.mailer = mailer
        return response

    def test_success_callback(self):
        response = self.post_callback(self.result(TransferStatus.SUCCESS, "200"))
        self.assertEqual(response.json(), {"status": "ok"})
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.SUCCESS)
        self.assertIsNotNone(withdrawal.completed_at)
        self.assertIsNotNone(withdrawal.callback_payload)
        self.assertEqual(self.mailer.return_value.send_template.call_args.kwargs["variables"]["status"], "success")
        # A duplicate callback changes nothing and sends no email.
        self.post_callback(self.result(TransferStatus.SUCCESS, "200"))
        self.mailer.return_value.send_template.assert_not_called()
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))

    def test_failed_callback_reverses(self):
        self.post_callback(self.result(TransferStatus.FAILED, "400", provider_message="Rejected by bank"))
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.FAILED)
        self.assertEqual(withdrawal.failure_reason, "Rejected by bank")
        self.assertEqual(self.wallet().available_balance, Decimal("150000"))
        self.post_callback(self.result(TransferStatus.FAILED, "400"))
        self.assertEqual(self.wallet().available_balance, Decimal("150000"))
        self.assertEqual(LedgerEntry.objects.filter(withdrawal=withdrawal).count(), 4)

    def test_success_after_failure_is_flagged(self):
        self.post_callback(self.result(TransferStatus.FAILED, "400"))
        self.post_callback(self.result(TransferStatus.SUCCESS, "200"))
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.FAILED)
        self.assertTrue(withdrawal.needs_review)

    def test_amount_mismatch_and_suspect_account_flagged(self):
        self.post_callback(self.result(TransferStatus.PROCESSING, "204", needs_review=True))
        self.assertTrue(Withdrawal.objects.get().needs_review)
        self.post_callback(self.result(TransferStatus.SUCCESS, "200", amount_received=Decimal("100000")))
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.SUCCESS)
        self.assertIn("100000", withdrawal.review_note)

    def test_unknown_withdrawal_ignored_and_invalid_signature_rejected(self):
        unknown = accepted(reference_no="WDR-X", provider_transfer_id="DISPTR-X", status=TransferStatus.SUCCESS)
        with self.assertLogs("apps.wallets.services", "ERROR"):
            self.assertEqual(self.post_callback(unknown).json(), {"status": "ignored"})
        with mock.patch(
            "apps.wallets.services.PaymentAggregator.parse_transfer_callback",
            side_effect=provider_errors.InvalidCallback("bad"),
        ), self.assertLogs("apps.wallets.services", "WARNING"):
            response = APIClient().post("/api/webhooks/dana/disbursement/", b"{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_unsigned_callback_applied_only_after_status_check(self):
        with mock.patch("apps.wallets.services.PaymentAggregator.confirm_transfer_callbacks", return_value=True), \
                mock.patch(
                    "apps.wallets.services.PaymentAggregator.get_transfer_status",
                    return_value=self.result(TransferStatus.SUCCESS, "00"),
                ) as status:
            response = self.post_callback(self.result(TransferStatus.FAILED, "35"))
        self.assertEqual(response.json(), {"status": "ok"})
        status.assert_called_once_with("DISPTR-1")
        # The provider's answer wins over the (forgeable) callback: no reversal.
        self.assertEqual(Withdrawal.objects.get().status, Withdrawal.Status.SUCCESS)

    def test_unsigned_callback_not_applied_when_unconfirmed(self):
        with mock.patch("apps.wallets.services.PaymentAggregator.confirm_transfer_callbacks", return_value=True), \
                mock.patch(
                    "apps.wallets.services.PaymentAggregator.get_transfer_status",
                    side_effect=provider_errors.ProviderUnavailable("down"),
                ), self.assertLogs("apps.wallets.services", "ERROR"):
            response = self.post_callback(self.result(TransferStatus.FAILED, "35"))
        self.assertEqual(response.json(), {"status": "unconfirmed"})
        withdrawal = Withdrawal.objects.get()
        self.assertEqual(withdrawal.status, Withdrawal.Status.PROCESSING)
        self.assertTrue(withdrawal.needs_review)
        self.assertFalse(LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.WITHDRAWAL_REVERSAL).exists())

    def test_poll_checks_old_withdrawal_without_id_by_derived_id(self):
        Withdrawal.objects.filter(pk=self.withdrawal.pk).update(provider_disbursement_id="")
        derived = mock.patch("apps.wallets.services.PaymentAggregator.transfer_id_for", return_value="WDR|014|527")
        # Still recent: the request may be in flight.
        with derived, mock.patch("apps.wallets.services.PaymentAggregator.get_transfer_status") as status:
            self.assertEqual(services.poll_processing_withdrawals(), 0)
        status.assert_not_called()

        Withdrawal.objects.filter(pk=self.withdrawal.pk).update(created_at=timezone.now() - datetime.timedelta(hours=1))
        with derived, mock.patch(
            "apps.wallets.services.PaymentAggregator.get_transfer_status",
            side_effect=provider_errors.TransferNotFound("no"),
        ):
            self.assertEqual(services.poll_processing_withdrawals(), 1)
        # Never reached the provider: left for resend / resolve.
        self.assertEqual(Withdrawal.objects.get().status, Withdrawal.Status.PROCESSING)

        with derived, mock.patch(
            "apps.wallets.services.PaymentAggregator.get_transfer_status",
            return_value=self.result(TransferStatus.SUCCESS, "00", provider_transfer_id="WDR|014|527"),
        ) as status, mock.patch(MAILER):
            self.assertEqual(services.poll_processing_withdrawals(), 1)
        status.assert_called_once_with("WDR|014|527")
        withdrawal = Withdrawal.objects.get()
        self.assertEqual((withdrawal.status, withdrawal.provider_disbursement_id), ("success", "WDR|014|527"))

    def test_poll_skips_withdrawal_without_id_when_not_derivable(self):
        Withdrawal.objects.filter(pk=self.withdrawal.pk).update(
            provider_disbursement_id="", created_at=timezone.now() - datetime.timedelta(hours=1)
        )
        with mock.patch("apps.wallets.services.PaymentAggregator.get_transfer_status") as status, \
                mock.patch("apps.wallets.services.PaymentAggregator.transfer_id_for", return_value=None):
            self.assertEqual(services.poll_processing_withdrawals(), 0)
        status.assert_not_called()

    def test_poll_syncs_processing_withdrawals(self):
        with mock.patch(
            "apps.wallets.services.PaymentAggregator.get_transfer_status",
            return_value=self.result(TransferStatus.SUCCESS, "200"),
        ) as status, mock.patch(MAILER):
            self.assertEqual(services.poll_processing_withdrawals(), 1)
        status.assert_called_once_with("DISPTR-1")
        self.assertEqual(Withdrawal.objects.get().status, Withdrawal.Status.SUCCESS)
        with mock.patch("apps.wallets.services.PaymentAggregator.get_transfer_status") as status:
            self.assertEqual(services.poll_processing_withdrawals(), 0)
        status.assert_not_called()


@override_settings(MAILJET_TEMPLATES=TEMPLATES)
class DanaWithdrawalTests(WalletFixtureMixin, TestCase):
    """A withdrawal through DANA Transfer to Bank, settled by its notification."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal as D

        from payment_aggregator.testing import FakeResponse, make_dana_provider

        from apps.payment_aggregator.aggregator import set_provider

        self.provider, self.session = make_dana_provider(
            FakeResponse(body={
                "responseCode": "2004200", "responseMessage": "Successful",
                "beneficiaryAccountName": "YAYASAN PENDIDIKAN",
                "additionalInfo": {"feeAmount": {"value": "2500.00", "currency": "IDR"}},
            }),
            FakeResponse(body={"responseCode": "2024300", "responseMessage": "Request In Progress"}),
            FakeResponse(body={
                "responseCode": "2000000", "responseMessage": "Successful",
                "originalPartnerReferenceNo": "set-below", "latestTransactionStatus": "00",
                "amount": {"value": "97500.00", "currency": "IDR"},
            }),
            disbursement_fee=D("2500"),
        )
        set_provider(self.provider)
        self.addCleanup(set_provider, None)
        otp = WithdrawalOtp.objects.create(
            reference="ref-dana", branch=self.branch, user=self.officer, amount=Decimal("100000"),
            code_hash="x", sent_to=self.branch.email, expires_at=timezone.now(), **NEW_ACCOUNT,
        )
        with mock.patch(MAILER):
            self.withdrawal = services._send_to_provider(
                services._create_processing_withdrawal(self.officer, otp, timezone.now())
            )

    def test_transfer_then_notification_confirmed_by_status_check(self):
        import json

        from payment_aggregator.testing import dana_notify_headers

        withdrawal = Withdrawal.objects.get()
        self.assertEqual((withdrawal.provider, withdrawal.status), ("dana", Withdrawal.Status.PROCESSING))
        self.assertEqual(withdrawal.provider_disbursement_id, withdrawal.withdrawal_no)
        sent = json.loads(self.session.calls[1]["data"])
        self.assertEqual((sent["beneficiaryBankCode"], sent["amount"]["value"]), ("014", "97500.00"))

        path = "/api/webhooks/v1.0/debit/emoney/transfer-bank/notify.htm"
        raw = json.dumps({"originalPartnerReferenceNo": withdrawal.withdrawal_no, "latestTransactionStatus": "06"}).encode()
        headers = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in dana_notify_headers(path, raw).items()}
        with mock.patch(MAILER):
            response = APIClient().post(path, raw, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["responseCode"], "2004300")
        # The status inquiry (00 = success) decides, not the notification body (06).
        self.assertEqual(json.loads(self.session.calls[2]["data"])["originalPartnerReferenceNo"], withdrawal.withdrawal_no)
        self.assertEqual(Withdrawal.objects.get().status, Withdrawal.Status.SUCCESS)
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))


class WithdrawalRaceTests(NoMailjetMixin, WalletFixtureMixin, TransactionTestCase):
    """Two withdrawals at once never take the balance below zero."""

    def test_concurrent_withdrawals(self):
        otps = []
        for index in range(2):
            otp = WithdrawalOtp.objects.create(
                reference=f"race-{index}", branch=self.branch, user=self.officer, amount=Decimal("100000"),
                code_hash=services._hash_otp(f"race-{index}", "123456"), sent_to=self.branch.email,
                expires_at=timezone.now() + datetime.timedelta(minutes=3), **NEW_ACCOUNT,
            )
            otps.append(otp)

        results = []
        barrier = threading.Barrier(2)

        def withdraw(reference):
            try:
                barrier.wait()
                services.create_withdrawal(self.officer, reference, "123456", True)
                results.append("ok")
            except Exception as error:  # noqa: BLE001
                results.append(getattr(error, "error_code", repr(error)))
            finally:
                connection.close()

        with mock.patch(TRANSFER, return_value=accepted()), mock.patch(MAILER):
            threads = [threading.Thread(target=withdraw, args=(otp.reference,)) for otp in otps]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(sorted(results), ["INSUFFICIENT_BALANCE", "ok"])
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))
        self.assertEqual(PayoutAccount.objects.count(), 1)


class PayoutAccountAdminWebTests(WalletFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.account = PayoutAccount.objects.create(branch=self.branch, **NEW_ACCOUNT)
        self.admin = User.objects.create_superuser(email="wl-admin@example.com", password=PASSWORD)
        self.client.force_login(self.admin)
        self.base = f"/admin-web/schools/{self.branch.school_id}/branches/{self.branch.pk}/"

    def test_branch_detail_lists_accounts(self):
        response = self.client.get(self.base)
        self.assertContains(response, "Payout accounts")
        self.assertContains(response, "5271234567")

    def test_edit_and_delete(self):
        url = f"{self.base}payout-accounts/{self.account.pk}/edit/"
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"bank_code": "BNI", "account_number": "1234567890", "account_holder_name": "BARU"})
        self.assertEqual(response.status_code, 302)
        self.account.refresh_from_db()
        self.assertEqual((self.account.bank_code, self.account.account_holder_name), ("BNI", "BARU"))

        response = self.client.post(f"{self.base}payout-accounts/{self.account.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PayoutAccount.objects.exists())

    def test_duplicate_account_rejected(self):
        other = PayoutAccount.objects.create(branch=self.branch, bank_code="BNI", account_number="999999", account_holder_name="X")
        response = self.client.post(
            f"{self.base}payout-accounts/{other.pk}/edit/",
            {"bank_code": "BCA", "account_number": "5271234567", "account_holder_name": "X"},
        )
        self.assertContains(response, "already has this bank account")

    def test_requires_superuser(self):
        self.client.force_login(self.officer)
        self.client.post(f"{self.base}payout-accounts/{self.account.pk}/delete/")
        self.assertTrue(PayoutAccount.objects.exists())
