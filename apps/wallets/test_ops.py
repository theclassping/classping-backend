"""Ops tools (Step 7): balance correction, admin wallet / withdrawal pages,
stuck withdrawals (resend / mark result) and the nightly balance check."""

import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from payment_aggregator import exceptions as provider_errors
from payment_aggregator.base import ProviderBalance
from apps.wallets.constants import OPS_ALERT_EMAIL
from apps.payment_gateway.tests import PASSWORD
from apps.users.models import User

from . import services
from .exceptions import InsufficientBalance, WithdrawalNotStuck
from .models import BranchWallet, LedgerEntry, Withdrawal, WithdrawalOtp
from .tests import MAILER, NEW_ACCOUNT, TEMPLATES, TRANSFER, WalletFixtureMixin, accepted

GET_BALANCE = "apps.wallets.services.PaymentAggregator.get_balance"


class BalanceAdjustmentTests(WalletFixtureMixin, TestCase):
    def test_adjustment_posts_entry_and_moves_available(self):
        entry = services.adjust_balance(self.officer, self.branch.pk, Decimal("-50000"), "Bank charge")
        self.assertEqual(entry.entry_type, LedgerEntry.EntryType.ADJUSTMENT)
        self.assertEqual((entry.created_by, entry.note), (self.officer, "Bank charge"))
        self.assertEqual(entry.balance_after, Decimal("100000"))
        self.assertEqual(self.wallet().available_balance, Decimal("100000"))

    def test_adjustment_cannot_make_balance_negative(self):
        with self.assertRaises(InsufficientBalance):
            services.adjust_balance(self.officer, self.branch.pk, Decimal("-150001"), "Too much")
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertEqual(self.wallet().available_balance, Decimal("150000"))


@override_settings(MAILJET_TEMPLATES=TEMPLATES)
class StuckWithdrawalTests(WalletFixtureMixin, TestCase):
    """A withdrawal whose /makedisbursement call timed out: no provider id."""

    def setUp(self):
        super().setUp()
        otp = WithdrawalOtp.objects.create(
            reference="ref-stuck", branch=self.branch, user=self.officer, amount=Decimal("100000"),
            code_hash="x", sent_to=self.branch.email, expires_at=timezone.now(), **NEW_ACCOUNT,
        )
        with mock.patch(TRANSFER, side_effect=provider_errors.ProviderUnavailable("timeout")), \
                mock.patch(MAILER), self.assertLogs("apps.wallets.services", "ERROR"):
            self.withdrawal = services._send_to_provider(
                services._create_processing_withdrawal(self.officer, otp, timezone.now())
            )
        self.admin = User.objects.create_superuser(email="wl-ops@example.com", password=PASSWORD)
        self.client.force_login(self.admin)
        self.url = "/admin-web/withdrawals/{}/".format(self.withdrawal.pk)

    def reload(self):
        self.withdrawal.refresh_from_db()
        return self.withdrawal

    def test_detail_offers_stuck_actions(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Stuck withdrawal")
        self.assertContains(response, "Resend to provider")
        self.assertContains(self.client.get("/admin-web/withdrawals/?flag=stuck"), self.withdrawal.withdrawal_no)

    def test_resend_accepted_gets_provider_id(self):
        with mock.patch(TRANSFER, return_value=accepted()) as transfer, mock.patch(MAILER):
            self.client.post(self.url + "resend/")
        self.assertEqual(transfer.call_args.args[0].reference_no, self.withdrawal.withdrawal_no)
        withdrawal = self.reload()
        self.assertEqual((withdrawal.status, withdrawal.provider_disbursement_id), ("processing", "DISPTR-1"))

    def test_resend_duplicate_stays_processing_for_dashboard_check(self):
        with mock.patch(TRANSFER, side_effect=provider_errors.DuplicateTransfer("dup")):
            self.client.post(self.url + "resend/")
        withdrawal = self.reload()
        self.assertEqual(withdrawal.status, Withdrawal.Status.PROCESSING)
        self.assertIn("duplicate", withdrawal.review_note)

    def test_mark_failed_returns_the_balance(self):
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))
        with mock.patch(MAILER):
            self.client.post(self.url + "mark-failed/", {"note": "Not found in the Rintisan dashboard"})
        withdrawal = self.reload()
        self.assertEqual(withdrawal.status, Withdrawal.Status.FAILED)
        self.assertEqual(withdrawal.failure_reason, "Not found in the Rintisan dashboard")
        self.assertFalse(withdrawal.needs_review)
        self.assertIn("wl-ops@example.com", withdrawal.review_note)
        self.assertEqual(self.wallet().available_balance, Decimal("150000"))

    def test_mark_success_keeps_the_debit(self):
        with mock.patch(MAILER):
            self.client.post(self.url + "mark-success/", {"note": "Paid out per dashboard"})
        withdrawal = self.reload()
        self.assertEqual(withdrawal.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(self.wallet().available_balance, Decimal("50000"))

    def test_note_required(self):
        self.client.post(self.url + "mark-failed/", {"note": ""})
        self.assertEqual(self.reload().status, Withdrawal.Status.PROCESSING)

    def test_only_stuck_withdrawals_can_be_resolved(self):
        Withdrawal.objects.filter(pk=self.withdrawal.pk).update(provider_disbursement_id="DISPTR-9")
        with self.assertRaises(WithdrawalNotStuck):
            services.resolve_withdrawal(self.admin, self.withdrawal.pk, True, "x")
        with self.assertRaises(WithdrawalNotStuck):
            services.resend_withdrawal(self.withdrawal.pk)

    def test_requires_superuser(self):
        self.client.force_login(self.officer)
        self.client.post(self.url + "mark-failed/", {"note": "x"})
        self.assertEqual(self.reload().status, Withdrawal.Status.PROCESSING)


class AdminWalletPageTests(WalletFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(email="wl-ops@example.com", password=PASSWORD)
        self.client.force_login(self.admin)

    def test_list_compares_provider_balance(self):
        low = ProviderBalance(available=Decimal("100000"), pending=Decimal("0"))
        with mock.patch(GET_BALANCE, return_value=low):
            response = self.client.get("/admin-web/wallets/")
        self.assertContains(response, "150000")
        self.assertContains(response, "lower than what branches can withdraw")
        with mock.patch(GET_BALANCE, side_effect=provider_errors.ProviderUnavailable("down")):
            self.assertContains(self.client.get("/admin-web/wallets/"), "Provider balance unavailable")

    def test_detail_posts_correction(self):
        url = "/admin-web/wallets/{}/".format(self.branch.pk)
        response = self.client.post(url, {"amount": "-200000", "note": "x"})
        self.assertContains(response, "negative")
        response = self.client.post(url, {"amount": "25000", "note": "Late cash deposit"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.wallet().available_balance, Decimal("175000"))
        self.assertContains(self.client.get(url), "Late cash deposit")


class BranchBalanceCheckTests(WalletFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        # Start from a wallet that matches its ledger.
        BranchWallet.objects.filter(branch=self.branch).update(available_balance=0)
        services.adjust_balance(self.officer, self.branch.pk, Decimal("150000"), "Opening balance")

    def test_matching_wallets_send_nothing(self):
        with mock.patch("apps.wallets.services.Mailer") as mailer:
            self.assertEqual(services.check_branch_balances(), [])
        mailer.assert_not_called()

    @override_settings(MAILJET_TEMPLATES={**TEMPLATES, "balance_alert": 103})
    def test_mismatch_is_logged_and_emailed(self):
        BranchWallet.objects.filter(branch=self.branch).update(available_balance=Decimal("140000"))
        with mock.patch("apps.wallets.services.Mailer") as mailer, \
                self.assertLogs("apps.wallets.services", "ERROR"):
            mismatches = services.check_branch_balances()
        self.assertEqual(len(mismatches), 1)
        self.assertIn("wallet total 140000", mismatches[0])
        kwargs = mailer.return_value.send_template.call_args.kwargs
        self.assertEqual((kwargs["to_email"], kwargs["template_id"]), (OPS_ALERT_EMAIL, 103))
        self.assertEqual(kwargs["variables"]["count"], 1)

    def test_only_branches_changed_that_day_are_checked(self):
        BranchWallet.objects.filter(branch=self.branch).update(available_balance=Decimal("1"))
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        self.assertEqual(services.check_branch_balances(day=yesterday), [])
