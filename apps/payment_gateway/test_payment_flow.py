"""Step 5: payment callback, settlement into the branch ledger, cancel."""

import threading
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payment_aggregator.aggregator import set_provider
from apps.payment_aggregator.base import BillingResult, BillingStatus, SettlementStatus
from apps.payment_aggregator.providers.rintisan import signing
from apps.payment_aggregator.tests.helpers import CLIENT_ID, key_pair, make_provider
from apps.payments.models import Payment, PaymentProof
from apps.student_invoices.models import StudentInvoice
from apps.users.models import User
from apps.wallets.models import BranchWallet, LedgerEntry

from . import services
from .models import GatewayPayment
from .tasks import send_payment_completed_email_task
from .test_checkout import CheckoutFixtureMixin

WEBHOOK_URL = "/api/webhooks/rintisan/payment/"
EMAIL_TASK = "apps.payment_gateway.tasks.send_payment_completed_email_task.delay"


def callback_body(payment_no="PAY-1", amount=130000, code="200", message="success", trx="PPI-1"):
    return (
        '{"timestamp":"2026-11-07 10:30:00","paid_at":"2026-11-07 10:02:41",'
        '"partner_trx_id":"%s","trx_id":"%s","payment_code":"988111",'
        '"total_amount":%d,"status":{"code":"%s","message":"%s"}}' % (payment_no, trx, amount, code, message)
    ).encode()


class PaymentFlowMixin(CheckoutFixtureMixin):
    def setUp(self):
        super().setUp()
        provider, _ = make_provider()
        set_provider(provider)
        self.addCleanup(set_provider, None)
        self.checkout_row = self.make_payment("PAY-1", "k1", provider_trx_id="PPI-1")
        self.add_item(self.checkout_row, self.invoice)
        self.add_item(self.checkout_row, self.invoice_2)

    def post_callback(self, raw, signed=True, token="callback-token"):
        headers = {"HTTP_X_CALLBACK_TOKEN": token}
        if signed:
            headers["HTTP_X_SIGNATURE"] = signing.sign(CLIENT_ID, raw, key_pair("rintisan")[0])
        return self.client.post(WEBHOOK_URL, raw, content_type="application/json", **headers)

    def reload(self):
        self.checkout_row.refresh_from_db()
        self.invoice.refresh_from_db()
        self.invoice_2.refresh_from_db()
        return self.checkout_row

    def wallet(self):
        return BranchWallet.objects.get(branch=self.branch)


class PaymentCallbackTests(PaymentFlowMixin, TestCase):
    def test_paid_callback_settles_invoices_credits_branch_and_emails(self):
        with mock.patch(EMAIL_TASK) as send_email:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post_callback(callback_body())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"status": "ok"})

        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.PAID)
        self.assertIsNotNone(checkout.paid_at)
        self.assertIsNotNone(checkout.callback_received_at)
        self.assertEqual(checkout.callback_payload["partner_trx_id"], "PAY-1")
        self.assertFalse(checkout.items.filter(is_active=True).exists())

        for invoice in (self.invoice, self.invoice_2):
            self.assertEqual(invoice.status, StudentInvoice.Status.PAID)
            self.assertEqual(invoice.amount_paid, invoice.total_amount)
            payment = Payment.objects.get(student_invoice=invoice)
            self.assertEqual(payment.payment_channel, Payment.PaymentChannel.PAYMENT_GATEWAY)
            self.assertEqual(payment.payment_method, Payment.PaymentMethod.VIRTUAL_ACCOUNT)
            self.assertEqual(payment.status, Payment.Status.COMPLETED)
            self.assertEqual(payment.gateway_payment, checkout)
            self.assertIsNone(payment.verified_by)

        entry = LedgerEntry.objects.get(gateway_payment=checkout)
        self.assertEqual(entry.entry_type, LedgerEntry.EntryType.PAYMENT_CREDIT)
        self.assertEqual(entry.amount, Decimal("125000.00"))  # invoice total, not the fee
        self.assertEqual(entry.settlement_status, LedgerEntry.SettlementStatus.PENDING_SETTLEMENT)
        self.assertEqual(self.wallet().pending_balance, Decimal("125000.00"))
        self.assertEqual(self.wallet().available_balance, Decimal("0"))

        self.assertEqual(
            sorted(call.args[0] for call in send_email.call_args_list),
            sorted(Payment.objects.filter(gateway_payment=checkout).values_list("pk", flat=True)),
        )

    def test_invalid_signature_or_token_is_rejected(self):
        self.assertEqual(self.post_callback(callback_body(), signed=False).status_code, 401)
        self.assertEqual(self.post_callback(callback_body(), token="wrong").status_code, 401)
        self.assertEqual(self.reload().status, GatewayPayment.Status.PENDING)
        self.assertFalse(LedgerEntry.objects.exists())

    def test_duplicate_callback_credits_once(self):
        for _ in range(2):
            self.assertEqual(self.post_callback(callback_body()).status_code, 200)
        self.assertEqual(Payment.objects.filter(gateway_payment=self.checkout_row).count(), 2)
        self.assertEqual(LedgerEntry.objects.filter(gateway_payment=self.checkout_row).count(), 1)
        self.assertEqual(self.wallet().pending_balance, Decimal("125000.00"))

    def test_amount_mismatch_is_flagged_not_settled(self):
        self.post_callback(callback_body(amount=1000))
        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.PENDING)
        self.assertTrue(checkout.needs_review)
        self.assertIn("does not match", checkout.review_note)
        self.assertFalse(Payment.objects.exists())

    def test_non_paid_callback_changes_nothing(self):
        # Rintisan sends no expiry callback; any non-paid body is ignored and
        # the expiry job decides.
        for code, message in (("201", "processing"), ("400", "expired")):
            self.post_callback(callback_body(code=code, message=message))
            self.assertEqual(self.reload().status, GatewayPayment.Status.PENDING)
            self.assertTrue(self.checkout_row.items.filter(is_active=True).exists())

    def test_unknown_checkout_is_ignored(self):
        response = self.post_callback(callback_body(payment_no="PAY-NOPE", trx="PPI-NOPE"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ignored"})


class SettlementRulesTests(PaymentFlowMixin, TestCase):
    def test_late_payment_after_cancel_still_settles_open_invoices(self):
        services.cancel_gateway_payment(self.parent_user, self.checkout_row.pk, "changed mind")
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.PAID)
        self.assertFalse(checkout.needs_refund)
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAID)

    def test_late_payment_after_manual_payment_needs_refund(self):
        services.cancel_gateway_payment(self.staff_user, self.checkout_row.pk, "Paid cash")
        manual = Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.CASH, status=Payment.Status.COMPLETED,
        )
        StudentInvoice.objects.filter(pk=self.invoice.pk).update(status=StudentInvoice.Status.PAID)

        services.mark_gateway_payment_paid(self.checkout_row.pk)
        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.PAID)
        self.assertTrue(checkout.needs_refund)
        self.assertIn(self.invoice.invoice_no, checkout.review_note)
        manual.refresh_from_db()
        self.assertEqual(manual.payment_channel, Payment.PaymentChannel.MANUAL)  # untouched
        self.assertEqual(self.invoice_2.status, StudentInvoice.Status.PAID)  # the other invoice settled
        # The money arrived, so the branch gets the full invoice total and
        # refunds the payer itself (manually, in cash).
        self.assertEqual(LedgerEntry.objects.get(gateway_payment=checkout).amount, Decimal("125000.00"))
        self.assertEqual(self.wallet().pending_balance, Decimal("125000.00"))

        staff = APIClient()
        staff.force_authenticate(user=self.staff_user)
        listing = staff.get("/api/gateway/payments/?needs_refund=true")
        self.assertEqual([row["id"] for row in listing.data], [checkout.pk])
        self.assertTrue(listing.data[0]["needs_refund"])
        detail = staff.get(f"/api/gateway/payments/{checkout.pk}/")
        self.assertIn(self.invoice.invoice_no, detail.data["review_note"])

    def expire_then_submit_manual(self, with_proof):
        """Checkout expired, then a manual payment was submitted for invoice."""
        services.mark_gateway_payment_expired(self.checkout_row.pk)
        manual = Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
        )
        StudentInvoice.objects.filter(pk=self.invoice.pk).update(status=StudentInvoice.Status.PAYMENT_SUBMITTED)
        if with_proof:
            PaymentProof.objects.create(payment=manual, image_data={"object_key": "transfer.png"})
        return manual

    def test_late_payment_settles_submitted_manual_payment_without_proof(self):
        manual = self.expire_then_submit_manual(with_proof=False)
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.PAID)
        self.assertFalse(checkout.needs_refund)
        manual.refresh_from_db()
        self.assertEqual(manual.payment_channel, Payment.PaymentChannel.PAYMENT_GATEWAY)
        self.assertEqual(manual.status, Payment.Status.COMPLETED)
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAID)

    def test_late_payment_with_manual_proof_awaiting_review_needs_refund(self):
        manual = self.expire_then_submit_manual(with_proof=True)
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.PAID)
        self.assertTrue(checkout.needs_refund)
        self.assertIn(self.invoice.invoice_no, checkout.review_note)
        manual.refresh_from_db()
        self.assertEqual(manual.payment_channel, Payment.PaymentChannel.MANUAL)  # untouched
        self.assertEqual(manual.status, Payment.Status.SUBMITTED)
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAYMENT_SUBMITTED)
        self.assertEqual(self.invoice_2.status, StudentInvoice.Status.PAID)  # other invoice settled

    def test_late_payment_after_rejected_manual_payment_with_proof_settles(self):
        services.mark_gateway_payment_expired(self.checkout_row.pk)
        rejected = Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.BANK_TRANSFER, status=Payment.Status.REJECTED,
            rejection_reason="Wrong amount",
        )
        PaymentProof.objects.create(payment=rejected, image_data={"object_key": "rejected.png"})
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        self.assertFalse(self.reload().needs_refund)
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAID)

    def test_rejected_manual_payment_becomes_gateway_row(self):
        rejected = Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.BANK_TRANSFER, status=Payment.Status.REJECTED,
            rejection_reason="Blurry",
        )
        PaymentProof.objects.create(payment=rejected, image_data={"object_key": "old.png"})
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        rejected.refresh_from_db()
        self.assertEqual(rejected.payment_channel, Payment.PaymentChannel.PAYMENT_GATEWAY)
        self.assertEqual(rejected.status, Payment.Status.COMPLETED)
        self.assertIsNone(rejected.rejection_reason)
        self.assertEqual(rejected.proofs.count(), 1)  # history kept

    def test_settlement_moves_pending_to_available(self):
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        unsettled = BillingResult("PAY-1", "PPI-1", status=BillingStatus.PAID)
        settled = BillingResult("PAY-1", "PPI-1", status=BillingStatus.PAID, settlement_status=SettlementStatus.SETTLED)

        with mock.patch("apps.payment_gateway.services.PaymentAggregator.get_billing_status", return_value=unsettled):
            self.assertEqual(services.reconcile_settlements(), 0)
        self.assertEqual(self.wallet().pending_balance, Decimal("125000.00"))

        with mock.patch("apps.payment_gateway.services.PaymentAggregator.get_billing_status", return_value=settled):
            self.assertEqual(services.reconcile_settlements(), 1)
            self.assertEqual(services.reconcile_settlements(), 0)  # idempotent
        wallet = self.wallet()
        self.assertEqual(wallet.pending_balance, Decimal("0"))
        self.assertEqual(wallet.available_balance, Decimal("125000.00"))
        self.assertIsNotNone(self.reload().settled_at)
        self.assertEqual(LedgerEntry.objects.get().settlement_status, LedgerEntry.SettlementStatus.SETTLED)

    def test_settlement_job_is_scheduled_hourly(self):
        from config.celery import app

        app.loader.import_default_modules()
        entry = app.conf.beat_schedule["reconcile_gateway_settlements"]
        self.assertEqual(entry["task"], "apps.payment_gateway.tasks.reconcile_settlements_task")
        self.assertEqual(entry["schedule"].minute, {15})
        self.assertEqual(len(entry["schedule"].hour), 24)
        self.assertIn(entry["task"], app.tasks)

    def test_sync_applies_provider_status(self):
        paid = BillingResult("PAY-1", "PPI-1", status=BillingStatus.PAID, amount=Decimal("130000"))
        with mock.patch("apps.payment_gateway.services.PaymentAggregator.get_billing_status", return_value=paid):
            services.sync_gateway_payment(self.checkout_row.pk)
        self.assertEqual(self.reload().status, GatewayPayment.Status.PAID)

    def test_sync_after_window_expires_unpaid_checkout(self):
        from datetime import timedelta
        from django.utils import timezone

        GatewayPayment.objects.filter(pk=self.checkout_row.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )
        unpaid = BillingResult("PAY-1", "PPI-1", status=BillingStatus.PENDING)
        with mock.patch("apps.payment_gateway.services.PaymentAggregator.get_billing_status", return_value=unpaid):
            services.sync_gateway_payment(self.checkout_row.pk)
        checkout = self.reload()
        self.assertEqual(checkout.status, GatewayPayment.Status.EXPIRED)
        self.assertFalse(checkout.items.filter(is_active=True).exists())

    def test_email_task_uses_shared_notification(self):
        services.mark_gateway_payment_paid(self.checkout_row.pk)
        payment = Payment.objects.filter(gateway_payment=self.checkout_row).first()
        with mock.patch("apps.payments.notifications.Mailer") as mailer:
            send_payment_completed_email_task.delay(payment.pk)
        kwargs = mailer.return_value.send_template.call_args.kwargs
        self.assertEqual(kwargs["variables"]["invoice_no"], payment.student_invoice.invoice_no)
        self.assertEqual(kwargs["variables"]["status"], "completed")


class CancelApiTests(PaymentFlowMixin, TestCase):
    def cancel(self, user, reason="Bayar tunai"):
        client = APIClient()
        client.force_authenticate(user=user)
        return client.post(f"/api/gateway/payments/{self.checkout_row.pk}/cancel/", {"reason": reason}, format="json")

    def test_guardian_cancels(self):
        response = self.cancel(self.second_parent_user)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(response.data["cancel_reason"], "Bayar tunai")
        checkout = self.reload()
        self.assertEqual(checkout.cancelled_by, self.second_parent_user)
        self.assertFalse(checkout.items.filter(is_active=True).exists())
        self.assertEqual(self.invoice.status, StudentInvoice.Status.UNPAID)  # invoice untouched

    def test_branch_officer_cancels(self):
        self.assertEqual(self.cancel(self.staff_user).status_code, 200)

    def test_not_allowed(self):
        self.assertEqual(self.cancel(self.teacher_user).status_code, 403)
        self.assertEqual(self.cancel(self.other_branch_staff).status_code, 404)
        self.assertEqual(self.cancel(self.other_parent_user).status_code, 404)
        self.assertEqual(self.reload().status, GatewayPayment.Status.PENDING)

    def test_only_pending(self):
        self.cancel(self.parent_user)
        response = self.cancel(self.parent_user)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "GATEWAY_PAYMENT_NOT_PENDING")


class GatewayAdminWebTests(PaymentFlowMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            email="gw-ops@example.com", password="StrongPassword123!", first_name="Ops", last_name="Admin",
        )
        self.client.force_login(self.admin)

    def test_list_and_detail(self):
        listing = self.client.get(reverse("admin_web:gateway_payment_list") + "?status=pending")
        self.assertContains(listing, "PAY-1")
        detail = self.client.get(reverse("admin_web:gateway_payment_detail", args=[self.checkout_row.pk]))
        self.assertContains(detail, "Sync status")
        self.assertContains(detail, "Cancel online payment")

    def test_cancel_and_sync_buttons(self):
        self.client.post(reverse("admin_web:gateway_payment_cancel", args=[self.checkout_row.pk]), {"reason": "ops"})
        self.assertEqual(self.reload().status, GatewayPayment.Status.CANCELLED)

        paid = BillingResult("PAY-1", "PPI-1", status=BillingStatus.PAID, amount=Decimal("130000"))
        with mock.patch("apps.payment_gateway.services.PaymentAggregator.get_billing_status", return_value=paid):
            self.client.post(reverse("admin_web:gateway_payment_sync", args=[self.checkout_row.pk]))
        self.assertEqual(self.reload().status, GatewayPayment.Status.PAID)

    def test_staff_cannot_open_ops_pages(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("admin_web:gateway_payment_list"))
        self.assertNotEqual(response.status_code, 200)


class PaymentRaceTests(PaymentFlowMixin, TransactionTestCase):
    def run_together(self, *functions):
        barrier = threading.Barrier(len(functions))
        errors = []

        def run(function):
            try:
                barrier.wait(5)
                function()
            except Exception as error:  # surfaced by the callers' assertions
                errors.append(error)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(function,)) for function in functions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        return errors

    def test_duplicate_callbacks_at_once_credit_once(self):
        errors = self.run_together(
            lambda: services.mark_gateway_payment_paid(self.checkout_row.pk),
            lambda: services.mark_gateway_payment_paid(self.checkout_row.pk),
        )
        self.assertEqual(errors, [])
        self.assertEqual(LedgerEntry.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)

    def test_payment_and_cancel_at_once_end_paid(self):
        errors = self.run_together(
            lambda: services.mark_gateway_payment_paid(self.checkout_row.pk),
            lambda: services.cancel_gateway_payment(self.parent_user, self.checkout_row.pk, "x"),
        )
        # Either cancel lost (409) or cancel won and the late payment still settled.
        self.assertLessEqual(len(errors), 1)
        self.assertEqual(self.reload().status, GatewayPayment.Status.PAID)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_payment_and_expiry_at_once_end_paid(self):
        errors = self.run_together(
            lambda: services.mark_gateway_payment_paid(self.checkout_row.pk),
            lambda: services.mark_gateway_payment_expired(self.checkout_row.pk),
        )
        self.assertEqual(errors, [])
        self.assertEqual(self.reload().status, GatewayPayment.Status.PAID)
