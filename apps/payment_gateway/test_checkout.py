import threading
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from payment_aggregator.base import BillingResult, BillingStatus
from payment_aggregator.exceptions import (
    DuplicateBilling,
    InvalidPayerPhone,
    ProviderRejected,
    ProviderUnavailable,
)
from apps.payments.exceptions import InvoiceLocked
from apps.payments.models import Payment
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student, StudentGuardian
from apps.classes.models import ClassStudent

from . import services
from .models import GatewayPayment
from .tasks import expire_gateway_payment_task
from .tests import GatewayFixtureMixin, NoMailjetMixin

CREATE_BILLING = "apps.payment_gateway.services.PaymentAggregator.create_billing"
GET_STATUS = "apps.payment_gateway.services.PaymentAggregator.get_billing_status"


def billing_result(reference_no="PAY-x", trx="PPI-261107-1", **extra):
    values = dict(
        reference_no=reference_no,
        provider_trx_id=trx,
        status=BillingStatus.PENDING,
        payment_code="9881234567890123",
        billing_url="https://billing.rintisan.co.id/penagihan/abc",
        raw={"response_code": "200", "trx_id": trx},
    )
    values.update(extra)
    return BillingResult(**values)


class CheckoutFixtureMixin(GatewayFixtureMixin):
    def setUp(self):
        super().setUp()
        self.branch.is_payment_gateway_enabled = True
        self.branch.save(update_fields=["is_payment_gateway_enabled"])
        self.guardian.phone_number = "0812-3456-7890"
        self.guardian.save(update_fields=["phone_number"])

        # A sibling (same guardian) for MIXED_STUDENT.
        self.sibling = Student.objects.create(
            first_name="Sari", last_name="Santoso", date_of_birth=date(2019, 1, 1),
            gender="female", enroll_date=date(2026, 7, 1), status="active", branch=self.branch,
        )
        StudentGuardian.objects.create(student=self.sibling, guardian=self.guardian, relationship="mother")
        sibling_class_student = ClassStudent.objects.create(
            class_obj=self.invoice.class_student.class_obj, student=self.sibling, is_current=True,
        )
        self.sibling_invoice = StudentInvoice.objects.create(
            class_student=sibling_class_student, fee_type=self.invoice.fee_type, invoice_no="INV-GW-SIB",
            invoice_date=date(2026, 11, 1), due_date=date(2026, 11, 30),
            subtotal=Decimal("50000"), total_amount=Decimal("50000"),
        )

        self.parent = APIClient()
        self.parent.force_authenticate(user=self.parent_user)

    def checkout(self, client=None, invoice_ids=None, channel="VABCA", key="key-1"):
        return (client or self.parent).post(
            "/api/gateway/checkout/",
            {"invoice_ids": invoice_ids or [self.invoice.pk, self.invoice_2.pk], "channel": channel},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

    def assertCode(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.data)
        self.assertEqual(response.data["code"], code)


# --- Payability & quote -----------------------------------------------------


class PayabilityTests(CheckoutFixtureMixin, TestCase):
    def reason(self, invoice):
        invoice.refresh_from_db()
        return services.get_invoice_payability(invoice).reason

    def test_unpaid_and_overdue_are_payable(self):
        self.assertIsNone(self.reason(self.invoice))
        self.invoice.status = StudentInvoice.Status.OVERDUE
        self.invoice.save(update_fields=["status"])
        self.assertIsNone(self.reason(self.invoice))

    def test_paid_and_manual_payments(self):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.CASH,
        )
        self.assertEqual(self.reason(self.invoice), services.NotPayableReason.MANUAL_PAYMENT_SUBMITTED)
        payment.status = Payment.Status.REJECTED
        payment.save(update_fields=["status"])
        self.assertIsNone(self.reason(self.invoice))  # rejected manual payment may be paid online
        payment.status = Payment.Status.COMPLETED
        payment.save(update_fields=["status"])
        self.assertEqual(self.reason(self.invoice), services.NotPayableReason.INVOICE_PAID)

    def test_locked_and_disabled(self):
        checkout = self.make_payment()
        self.add_item(checkout, self.invoice)
        payability = services.get_invoice_payability(self.invoice)
        self.assertEqual(payability.reason, services.NotPayableReason.INVOICE_LOCKED)
        self.assertEqual(payability.locked_by, checkout)

        self.branch.is_payment_gateway_enabled = False
        self.branch.save(update_fields=["is_payment_gateway_enabled"])
        self.assertEqual(self.reason(self.invoice_2), services.NotPayableReason.GATEWAY_DISABLED)

    def test_quote_totals_and_channels(self):
        quote = services.get_checkout_quote(self.parent_user, [self.invoice_2.pk, self.invoice.pk])
        self.assertEqual(quote.invoice_total, Decimal("125000"))
        channels = {channel.channel_code: channel for channel in quote.channels}
        self.assertNotIn("QRIS", channels)
        self.assertEqual(channels["VABCA"].amount, Decimal("130000.00"))
        self.assertEqual(channels["CC"].amount, Decimal("127552.00"))  # ceil(125000*100/98 = 127551.02)


# --- B0 / B1 ------------------------------------------------------------------


class InvoiceAndChannelApiTests(CheckoutFixtureMixin, TestCase):
    def test_invoices_lists_payability(self):
        checkout = self.make_payment()
        self.add_item(checkout, self.invoice_2)
        response = self.parent.get(f"/api/gateway/invoices/?student_id={self.student.pk}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["student_id"], self.student.pk)
        self.assertTrue(response.data["is_payment_gateway_enabled"])
        self.assertEqual(response.data["payment_window_minutes"], 60)
        rows = {row["id"]: row for row in response.data["invoices"]}
        self.assertTrue(rows[self.invoice.pk]["payable"])
        self.assertIsNone(rows[self.invoice.pk]["locked_until"])
        self.assertFalse(rows[self.invoice_2.pk]["payable"])
        self.assertEqual(rows[self.invoice_2.pk]["not_payable_reason"], "INVOICE_LOCKED")
        self.assertEqual(rows[self.invoice_2.pk]["active_gateway_payment_id"], checkout.pk)

    def test_invoices_requires_student_and_scope(self):
        self.assertCode(self.parent.get("/api/gateway/invoices/"), 400, "STUDENT_REQUIRED")
        other = APIClient()
        other.force_authenticate(user=self.other_parent_user)
        self.assertEqual(other.get(f"/api/gateway/invoices/?student_id={self.student.pk}").status_code, 404)
        teacher = APIClient()
        teacher.force_authenticate(user=self.teacher_user)
        self.assertEqual(teacher.get(f"/api/gateway/invoices/?student_id={self.student.pk}").status_code, 403)

    def test_channels(self):
        response = self.parent.get(f"/api/gateway/channels/?invoice_ids={self.invoice.pk},{self.invoice_2.pk}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["invoice_total"], "125000.00")
        self.assertEqual(response.data["invoice_ids"], sorted([self.invoice.pk, self.invoice_2.pk]))
        codes = [channel["code"] for channel in response.data["channels"]]
        self.assertIn("VABCA", codes)
        self.assertNotIn("QRIS", codes)

    def test_channels_show_payment_deadline(self):
        before = timezone.now()
        response = self.parent.get(f"/api/gateway/channels/?invoice_ids={self.invoice.pk}")
        self.assertEqual(response.data["payment_window_minutes"], 60)
        # ISO 8601 with the WIB offset, e.g. "2026-11-07T10:45:00.123456+07:00"
        self.assertTrue(response.data["expires_at"].endswith("+07:00"), response.data["expires_at"])
        expires_at = datetime.fromisoformat(response.data["expires_at"])
        self.assertAlmostEqual((expires_at - before).total_seconds(), 3600, delta=5)

    def test_channels_validation(self):
        self.assertCode(self.parent.get("/api/gateway/channels/?invoice_ids="), 400, "INVALID_INVOICE_IDS")
        self.assertCode(self.parent.get("/api/gateway/channels/?invoice_ids=1,2,3,4,5,6"), 400, "INVALID_INVOICE_IDS")
        self.assertCode(self.parent.get("/api/gateway/channels/?invoice_ids=a,b"), 400, "INVALID_INVOICE_IDS")
        self.assertCode(
            self.parent.get(f"/api/gateway/channels/?invoice_ids={self.invoice.pk},{self.sibling_invoice.pk}"),
            400, "MIXED_STUDENT",
        )
        self.assertEqual(self.parent.get("/api/gateway/channels/?invoice_ids=999999").status_code, 404)

    def test_channels_locked_invoice(self):
        checkout = self.make_payment()
        self.add_item(checkout, self.invoice)
        response = self.parent.get(f"/api/gateway/channels/?invoice_ids={self.invoice.pk}")
        self.assertCode(response, 400, "INVOICE_LOCKED")
        self.assertIn("WIB", response.data["detail"])

    def test_channels_gateway_disabled(self):
        self.branch.is_payment_gateway_enabled = False
        self.branch.save(update_fields=["is_payment_gateway_enabled"])
        self.assertCode(self.parent.get(f"/api/gateway/channels/?invoice_ids={self.invoice.pk}"), 400, "GATEWAY_DISABLED")


# --- B2 -----------------------------------------------------------------------


@mock.patch.object(expire_gateway_payment_task, "apply_async")
class CheckoutApiTests(CheckoutFixtureMixin, TestCase):
    def test_checkout_creates_billing(self, apply_async):
        with mock.patch(CREATE_BILLING, return_value=billing_result()) as create_billing:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.checkout()
        self.assertEqual(response.status_code, 201, response.data)

        payment = GatewayPayment.objects.get(pk=response.data["id"])
        self.assertRegex(payment.payment_no, r"^PAY-\d{8}-\d{6}$")
        self.assertEqual(payment.status, GatewayPayment.Status.PENDING)
        self.assertEqual(payment.guardian, self.guardian)
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.provider, "rintisan")
        self.assertEqual(payment.amount, Decimal("130000.00"))
        self.assertEqual(payment.provider_trx_id, "PPI-261107-1")
        self.assertEqual(payment.items.filter(is_active=True).count(), 2)
        self.assertAlmostEqual(
            (payment.expires_at - payment.created_at).total_seconds(), 3600, delta=5
        )

        request = create_billing.call_args.args[0]
        self.assertEqual(request.reference_no, payment.payment_no)
        self.assertEqual(request.amount, Decimal("130000.00"))
        self.assertEqual(request.payer_phone, "6281234567890")
        self.assertEqual(request.payer_name, self.guardian.name)
        self.assertEqual(request.expires_at, payment.expires_at)
        self.assertIn("INV-GW-001", request.note)

        apply_async.assert_called_once_with(
            args=[payment.pk], eta=payment.expires_at + timedelta(minutes=2),
        )
        data = response.data
        self.assertEqual(data["payment_code"], "9881234567890123")
        self.assertEqual(data["billing_url"], "https://billing.rintisan.co.id/penagihan/abc")
        self.assertEqual(data["channel_name"], "BCA Virtual Account")
        self.assertEqual(data["student_name"], "Budi Santoso")
        self.assertEqual(len(data["items"]), 2)

    def test_long_payment_link_is_stored(self, apply_async):
        # Tokopedia CC returns OneLink deep links well over 1000 characters.
        long_link = "https://tokopedia.onelink.me/2ZX3?af_web_dp=" + "x" * 2000
        with mock.patch(CREATE_BILLING, return_value=billing_result(payment_link=long_link)):
            response = self.checkout()
        self.assertEqual(response.status_code, 201, response.data)
        payment = GatewayPayment.objects.get(pk=response.data["id"])
        self.assertEqual(payment.payment_link, long_link)

    def test_same_idempotency_key_returns_same_checkout(self, apply_async):
        with mock.patch(CREATE_BILLING, return_value=billing_result()) as create_billing:
            first = self.checkout()
            again = self.checkout()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["id"], first.data["id"])
        create_billing.assert_called_once()

    def test_same_key_different_request_conflicts(self, apply_async):
        with mock.patch(CREATE_BILLING, return_value=billing_result()):
            self.checkout()
            self.assertCode(self.checkout(invoice_ids=[self.invoice.pk]), 409, "IDEMPOTENCY_KEY_REUSED")
            self.assertCode(self.checkout(channel="VABNI"), 409, "IDEMPOTENCY_KEY_REUSED")

    def test_idempotency_key_required(self, apply_async):
        response = self.parent.post(
            "/api/gateway/checkout/", {"invoice_ids": [self.invoice.pk], "channel": "VABCA"}, format="json"
        )
        self.assertCode(response, 400, "IDEMPOTENCY_KEY_REQUIRED")

    def test_only_guardians_of_the_student_can_checkout(self, apply_async):
        staff = APIClient()
        staff.force_authenticate(user=self.staff_user)
        self.assertEqual(self.checkout(client=staff).status_code, 403)  # no create grant
        other = APIClient()
        other.force_authenticate(user=self.other_parent_user)
        self.assertEqual(self.checkout(client=other).status_code, 404)  # not visible
        self.assertFalse(GatewayPayment.objects.exists())

    def test_more_than_five_invoices_rejected(self, apply_async):
        self.assertCode(self.checkout(invoice_ids=[1, 2, 3, 4, 5, 6]), 400, "INVALID_INVOICE_IDS")

    def test_invalid_phone_rejected_before_anything_is_created(self, apply_async):
        self.guardian.phone_number = ""
        self.guardian.save(update_fields=["phone_number"])
        with mock.patch(CREATE_BILLING) as create_billing:
            self.assertCode(self.checkout(), 400, "PAYER_PHONE_INVALID")
        create_billing.assert_not_called()
        self.assertFalse(GatewayPayment.objects.exists())

    def test_qris_not_available(self, apply_async):
        self.assertCode(self.checkout(channel="QRIS"), 400, "CHANNEL_NOT_AVAILABLE")

    def test_manual_payment_submitted_not_payable(self, apply_async):
        Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.CASH,
        )
        self.assertCode(self.checkout(), 400, "INVOICE_NOT_PAYABLE")

    def test_provider_timeout_marks_failed_and_releases_invoices(self, apply_async):
        with mock.patch(CREATE_BILLING, side_effect=ProviderUnavailable("timeout")):
            response = self.checkout()
        self.assertCode(response, 503, "PROVIDER_UNAVAILABLE")
        payment = GatewayPayment.objects.get(pk=response.data["gateway_payment_id"])
        self.assertEqual(payment.status, GatewayPayment.Status.FAILED)
        self.assertFalse(payment.items.filter(is_active=True).exists())
        self.assertIsNone(services.get_invoice_payability(self.invoice).reason)
        apply_async.assert_not_called()

        # A new attempt (new key) works.
        with mock.patch(CREATE_BILLING, return_value=billing_result(trx="PPI-2")):
            self.assertEqual(self.checkout(key="key-2").status_code, 201)

    def test_provider_rejection_and_foreign_phone(self, apply_async):
        with mock.patch(CREATE_BILLING, side_effect=ProviderRejected("bad", provider_message="x")):
            response = self.checkout()
        self.assertCode(response, 400, "PROVIDER_REJECTED")
        self.assertEqual(GatewayPayment.objects.get(pk=response.data["gateway_payment_id"]).status, "failed")

        with mock.patch(CREATE_BILLING, side_effect=InvalidPayerPhone("not 62")):
            response = self.checkout(key="key-2")
        self.assertCode(response, 400, "PAYER_PHONE_INVALID")
        self.assertEqual(GatewayPayment.objects.get(pk=response.data["gateway_payment_id"]).status, "failed")

    def test_duplicate_billing_is_fetched_not_recreated(self, apply_async):
        with mock.patch(CREATE_BILLING, side_effect=DuplicateBilling("dup", provider_trx_id="PPI-EXISTING")):
            with mock.patch(GET_STATUS, return_value=billing_result(trx="PPI-EXISTING")) as get_status:
                response = self.checkout()
        self.assertEqual(response.status_code, 201, response.data)
        get_status.assert_called_once_with("PPI-EXISTING")
        self.assertEqual(GatewayPayment.objects.get(pk=response.data["id"]).provider_trx_id, "PPI-EXISTING")

    def test_rejected_manual_payment_can_be_paid_online(self, apply_async):
        Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.CASH, status=Payment.Status.REJECTED,
            rejection_reason="Blurry",
        )
        with mock.patch(CREATE_BILLING, return_value=billing_result()):
            self.assertEqual(self.checkout(invoice_ids=[self.invoice.pk]).status_code, 201)


# --- B3 / B4 ------------------------------------------------------------------


class GatewayPaymentApiTests(CheckoutFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.pending = self.make_payment("PAY-1", "k1", payment_code="988111")
        self.add_item(self.pending, self.invoice)
        self.paid = self.make_payment("PAY-2", "k2", status=GatewayPayment.Status.PAID, guardian=self.second_guardian)
        self.add_item(self.paid, self.invoice_2, is_active=False)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_list_for_every_guardian_of_the_student(self):
        for user in (self.parent_user, self.second_parent_user):
            response = self.client_for(user).get("/api/gateway/payments/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual({row["id"] for row in response.data}, {self.pending.pk, self.paid.pk})
        row = next(row for row in response.data if row["id"] == self.pending.pk)
        self.assertEqual(row["invoice_count"], 1)
        self.assertNotIn("payment_code", row)

    def test_list_filters(self):
        response = self.parent.get("/api/gateway/payments/?status=paid")
        self.assertEqual([row["id"] for row in response.data], [self.paid.pk])
        response = self.parent.get(f"/api/gateway/payments/?student_id={self.sibling.pk}")
        self.assertEqual(response.data, [])
        self.assertEqual(self.parent.get("/api/gateway/payments/?needs_refund=true").data, [])
        self.assertFalse(self.parent.get("/api/gateway/payments/").data[0]["needs_refund"])

    def test_scope(self):
        self.assertEqual(self.client_for(self.other_parent_user).get("/api/gateway/payments/").data, [])
        staff = self.client_for(self.staff_user).get("/api/gateway/payments/?search=PAY-1")
        self.assertEqual([row["id"] for row in staff.data], [self.pending.pk])
        self.assertEqual(self.client_for(self.other_branch_staff).get("/api/gateway/payments/").data, [])
        self.assertEqual(self.client_for(self.teacher_user).get("/api/gateway/payments/").status_code, 403)

    def test_detail(self):
        response = self.parent.get(f"/api/gateway/payments/{self.pending.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["payment_code"], "988111")
        self.assertEqual(response.data["items"][0]["invoice_no"], self.invoice.invoice_no)
        self.assertEqual(
            self.client_for(self.other_parent_user).get(f"/api/gateway/payments/{self.pending.pk}/").status_code,
            404,
        )

    def test_read_only(self):
        self.assertEqual(self.parent.delete(f"/api/gateway/payments/{self.pending.pk}/").status_code, 403)
        self.assertEqual(
            self.client_for(self.staff_user).patch(f"/api/gateway/payments/{self.pending.pk}/", {}).status_code,
            403,
        )


# --- Concurrency ------------------------------------------------------------


class CheckoutRaceTests(NoMailjetMixin, CheckoutFixtureMixin, TransactionTestCase):
    def test_two_checkouts_for_the_same_invoice(self):
        self.second_guardian.phone_number = "081298765432"
        self.second_guardian.save(update_fields=["phone_number"])
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt(user, key):
            try:
                barrier.wait(5)
                payment, _ = services.create_gateway_checkout(user, [self.invoice.pk], "VABCA", key)
                outcomes.append(("ok", payment.pk))
            except InvoiceLocked:
                outcomes.append(("locked", None))
            except Exception as error:  # pragma: no cover - surfaced by the assertion
                outcomes.append(("error", repr(error)))
            finally:
                connection.close()

        with mock.patch(CREATE_BILLING, side_effect=lambda request: billing_result(
            reference_no=request.reference_no, trx="PPI-" + request.reference_no,
        )), mock.patch.object(expire_gateway_payment_task, "apply_async"):
            threads = [
                threading.Thread(target=attempt, args=(self.parent_user, "race-1")),
                threading.Thread(target=attempt, args=(self.second_parent_user, "race-2")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)

        self.assertEqual(sorted(kind for kind, _ in outcomes), ["locked", "ok"], outcomes)
        self.assertEqual(GatewayPayment.objects.filter(items__student_invoice=self.invoice, items__is_active=True).count(), 1)


class CorsTests(TestCase):
    def test_browser_may_send_idempotency_key(self):
        response = self.client.options(
            "/api/gateway/checkout/",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type,idempotency-key",
        )
        allowed = response["access-control-allow-headers"].lower()
        self.assertIn("idempotency-key", allowed)
        self.assertIn("authorization", allowed)
