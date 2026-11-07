import datetime
import threading
from unittest import mock

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.payment_aggregator.base import BillingResult, BillingStatus
from apps.payment_aggregator.exceptions import BillingNotFound, ProviderUnavailable

from . import services
from .models import GatewayPayment, GatewayPaymentItem
from .tasks import expire_gateway_payment_task
from .tests import GatewayFixtureMixin

GET_STATUS = "apps.payment_gateway.services.PaymentAggregator.get_billing_status"


def billing(status):
    return BillingResult(reference_no="PAY-1", provider_trx_id="PPI-1", status=status)


class ExpiryFixtureMixin(GatewayFixtureMixin):
    def checkout(self, status=GatewayPayment.Status.PENDING, expired=True, provider_trx_id="PPI-1", no="PAY-1"):
        now = timezone.now()
        payment = self.make_payment(
            no,
            "key-" + no,
            status=status,
            provider_trx_id=provider_trx_id,
            expires_at=now - datetime.timedelta(minutes=1) if expired else now + datetime.timedelta(minutes=30),
        )
        self.add_item(payment, self.invoice)
        return payment

    def assertExpired(self, payment):
        payment.refresh_from_db()
        self.assertEqual(payment.status, GatewayPayment.Status.EXPIRED)
        self.assertFalse(payment.items.filter(is_active=True).exists())

    def assertUnchanged(self, payment, status=GatewayPayment.Status.PENDING):
        payment.refresh_from_db()
        self.assertEqual(payment.status, status)


class StateMachineTests(TestCase):
    def test_transitions(self):
        S = GatewayPayment.Status
        cases = {
            (S.PENDING, S.EXPIRED): True,
            (S.PENDING, S.CANCELLED): True,
            (S.PENDING, S.PAID): True,
            (S.EXPIRED, S.PAID): True,
            (S.CANCELLED, S.PAID): True,
            (S.EXPIRED, S.EXPIRED): False,
            (S.EXPIRED, S.CANCELLED): False,
            (S.CANCELLED, S.EXPIRED): False,
            (S.PAID, S.EXPIRED): False,
            (S.PAID, S.CANCELLED): False,
            (S.PAID, S.PAID): False,
        }
        for (current, new), allowed in cases.items():
            self.assertEqual(GatewayPayment(status=current).can_transition_to(new), allowed, msg=f"{current}->{new}")


class ExpireGatewayPaymentTests(ExpiryFixtureMixin, TestCase):
    def test_unpaid_at_provider_is_expired(self):
        payment = self.checkout()
        with mock.patch(GET_STATUS, return_value=billing(BillingStatus.PENDING)) as get_status:
            services.expire_gateway_payment(payment.pk)
        get_status.assert_called_once_with("PPI-1")
        self.assertExpired(payment)

    def test_expired_at_provider_is_expired(self):
        payment = self.checkout()
        with mock.patch(GET_STATUS, return_value=billing(BillingStatus.EXPIRED)):
            services.expire_gateway_payment(payment.pk)
        self.assertExpired(payment)

    def test_paid_at_provider_is_never_expired(self):
        payment = self.checkout()
        with mock.patch(GET_STATUS, return_value=billing(BillingStatus.PAID)):
            services.expire_gateway_payment(payment.pk)
        self.assertUnchanged(payment)
        self.assertTrue(payment.items.filter(is_active=True).exists())

    def test_billing_never_created_is_expired_without_query(self):
        payment = self.checkout(provider_trx_id=None)
        with mock.patch(GET_STATUS) as get_status:
            services.expire_gateway_payment(payment.pk)
        get_status.assert_not_called()
        self.assertExpired(payment)

    def test_billing_unknown_at_provider_is_expired(self):
        payment = self.checkout()
        with mock.patch(GET_STATUS, side_effect=BillingNotFound("x")):
            services.expire_gateway_payment(payment.pk)
        self.assertExpired(payment)

    def test_provider_down_leaves_checkout_pending(self):
        payment = self.checkout()
        with mock.patch(GET_STATUS, side_effect=ProviderUnavailable("down")):
            with self.assertRaises(ProviderUnavailable):
                services.expire_gateway_payment(payment.pk)
        self.assertUnchanged(payment)

    def test_before_expiry_nothing_happens(self):
        payment = self.checkout(expired=False)
        with mock.patch(GET_STATUS) as get_status:
            services.expire_gateway_payment(payment.pk)
        get_status.assert_not_called()
        self.assertUnchanged(payment)

    def test_final_statuses_are_left_alone(self):
        for index, status in enumerate((
            GatewayPayment.Status.PAID,
            GatewayPayment.Status.EXPIRED,
            GatewayPayment.Status.CANCELLED,
        )):
            payment = self.make_payment(f"PAY-F{index}", f"key-f{index}", status=status, provider_trx_id=f"PPI-F{index}")
            with mock.patch(GET_STATUS) as get_status:
                services.expire_gateway_payment(payment.pk)
            get_status.assert_not_called()
            self.assertUnchanged(payment, status)

    def test_mark_expired_twice_is_safe(self):
        payment = self.checkout()
        services.mark_gateway_payment_expired(payment.pk)
        services.mark_gateway_payment_expired(payment.pk)
        self.assertExpired(payment)

    def test_expired_checkout_releases_invoice_for_manual_payment(self):
        from apps.payments.services import ensure_invoice_open_for_manual_payment

        payment = self.checkout()
        services.mark_gateway_payment_expired(payment.pk)
        ensure_invoice_open_for_manual_payment(self.invoice)  # does not raise


class ExpiryTaskTests(ExpiryFixtureMixin, TestCase):
    def test_task_expires_checkout(self):
        payment = self.checkout()
        with mock.patch(GET_STATUS, return_value=billing(BillingStatus.PENDING)):
            result = expire_gateway_payment_task.delay(payment.pk).get()
        self.assertEqual(result, GatewayPayment.Status.EXPIRED)
        self.assertExpired(payment)

    def test_task_for_deleted_checkout_is_ignored(self):
        self.assertIsNone(expire_gateway_payment_task.delay(999999).get())

    def test_task_running_early_is_retried_after_window(self):
        payment = self.checkout(expired=False)
        with mock.patch.object(expire_gateway_payment_task, "retry", side_effect=RuntimeError("retry")) as retry:
            with self.assertRaises(RuntimeError):
                expire_gateway_payment_task.delay(payment.pk).get()
        self.assertEqual(retry.call_args.kwargs["eta"], services.expiry_check_time(payment))
        self.assertUnchanged(payment)

    def test_task_retries_when_provider_down(self):
        self.assertIn(ProviderUnavailable, expire_gateway_payment_task.autoretry_for)


class ScheduleExpiryTests(ExpiryFixtureMixin, TestCase):
    def test_job_queued_after_commit_for_expires_at_plus_delay(self):
        payment = self.checkout(expired=False)
        with mock.patch.object(expire_gateway_payment_task, "apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                services.schedule_gateway_payment_expiry(payment)
                apply_async.assert_not_called()  # only after commit
        apply_async.assert_called_once_with(
            args=[payment.pk],
            eta=payment.expires_at + datetime.timedelta(minutes=2),
        )

    @override_settings(CELERY_BROKER_URL="", CELERY_TASK_ALWAYS_EAGER=False)
    def test_no_broker_skips_queueing(self):
        payment = self.checkout(expired=False)
        with mock.patch.object(expire_gateway_payment_task, "apply_async") as apply_async:
            with self.assertLogs("apps.payment_gateway.services", "WARNING"):
                with self.captureOnCommitCallbacks(execute=True):
                    services.schedule_gateway_payment_expiry(payment)
        apply_async.assert_not_called()

    def test_broker_error_does_not_fail_caller(self):
        payment = self.checkout(expired=False)
        with mock.patch.object(expire_gateway_payment_task, "apply_async", side_effect=ConnectionError("down")):
            with self.assertLogs("apps.payment_gateway.services", "ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    services.schedule_gateway_payment_expiry(payment)


class ExpiryRaceTests(ExpiryFixtureMixin, TransactionTestCase):
    """Real row locks on Postgres: concurrent updates never overwrite each other."""

    def run_concurrently(self, holder, waiter):
        """``holder`` locks the row first; ``waiter`` starts while it is held."""
        locked = threading.Event()
        release = threading.Event()
        errors = []

        def hold():
            try:
                with transaction.atomic():
                    holder(locked)
                    release.wait(5)
            except Exception as error:  # pragma: no cover - surfaced below
                errors.append(error)
            finally:
                connection.close()

        def wait_for_lock():
            try:
                waiter()
            except Exception as error:  # pragma: no cover
                errors.append(error)
            finally:
                connection.close()

        first = threading.Thread(target=hold)
        first.start()
        self.assertTrue(locked.wait(5))
        second = threading.Thread(target=wait_for_lock)
        second.start()
        second.join(0.5)
        self.assertTrue(second.is_alive(), "waiter should block on the row lock")
        release.set()
        first.join(5)
        second.join(5)
        self.assertEqual(errors, [])

    def test_paid_while_expiry_job_waits_is_not_overwritten(self):
        payment = self.checkout()

        def webhook_marks_paid(locked):
            row = GatewayPayment.objects.select_for_update().get(pk=payment.pk)
            locked.set()
            row.status = GatewayPayment.Status.PAID
            row.save(update_fields=["status"])

        self.run_concurrently(webhook_marks_paid, lambda: services.mark_gateway_payment_expired(payment.pk))
        self.assertUnchanged(payment, GatewayPayment.Status.PAID)
        self.assertTrue(GatewayPaymentItem.objects.filter(gateway_payment=payment, is_active=True).exists())

    def test_two_expiries_at_once_apply_once(self):
        payment = self.checkout()
        calls = []
        original = GatewayPayment.save

        def counting_save(instance, *args, **kwargs):
            if instance.pk == payment.pk and instance.status == GatewayPayment.Status.EXPIRED:
                calls.append(1)
            return original(instance, *args, **kwargs)

        def first_expiry(locked):
            row = GatewayPayment.objects.select_for_update().get(pk=payment.pk)
            locked.set()
            row.status = GatewayPayment.Status.EXPIRED
            counting_save(row, update_fields=["status"])

        with mock.patch.object(GatewayPayment, "save", counting_save):
            self.run_concurrently(first_expiry, lambda: services.mark_gateway_payment_expired(payment.pk))
        self.assertEqual(len(calls), 1)
        self.assertUnchanged(payment, GatewayPayment.Status.EXPIRED)
