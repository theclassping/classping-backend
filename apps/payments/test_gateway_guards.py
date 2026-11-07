"""Guards that keep the manual payments API apart from the payment gateway."""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.payment_gateway.models import GatewayPayment
from apps.payment_gateway.tests import GatewayFixtureMixin
from apps.payments.models import Payment, PaymentProof
from apps.student_invoices.models import StudentInvoice
from apps.users.models import User

PROOF = {"object_key": "proofs/test.png", "filename": "test.png"}


@patch("apps.payments.serializers.Mailer")
class PaymentGatewayGuardApiTests(GatewayFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.parent = APIClient()
        self.parent.force_authenticate(user=self.parent_user)
        self.staff = APIClient()
        self.staff.force_authenticate(user=self.staff_user)
        # Existing role grants: only admins may DELETE payments / proofs and
        # parents may not PATCH payments, so those cases run as admin.
        self.admin = APIClient()
        self.admin.force_authenticate(user=User.objects.create_superuser(
            email="gw-guard-api-admin@example.com", password="StrongPassword123!",
            first_name="Guard", last_name="Admin",
        ))

    # --- helpers ---------------------------------------------------------

    def lock(self, invoice, status=GatewayPayment.Status.PENDING, is_active=True, no="PAY-LOCK"):
        checkout = self.make_payment(no, "key-" + no, status=status)
        self.add_item(checkout, invoice, is_active=is_active)
        return checkout

    def gateway_payment_row(self):
        checkout = self.make_payment("PAY-PAID", "key-paid", status=GatewayPayment.Status.PAID)
        self.add_item(checkout, self.invoice, is_active=False)
        return Payment.objects.create(
            student_invoice=self.invoice,
            amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.VIRTUAL_ACCOUNT,
            payment_channel=Payment.PaymentChannel.PAYMENT_GATEWAY,
            gateway_payment=checkout,
            status=Payment.Status.COMPLETED,
        )

    def rejected_manual_payment(self):
        return Payment.objects.create(
            student_invoice=self.invoice,
            amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
            status=Payment.Status.REJECTED,
            rejection_reason="Blurry proof",
        )

    def create_manual(self, client, invoice=None):
        invoice = invoice or self.invoice
        return client.post("/api/payments/", {
            "student_invoice_id": invoice.id,
            "amount": str(invoice.total_amount),
            "payment_method": "cash",
        }, format="json")

    def assertCode(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.data)
        self.assertEqual(response.data["code"], code)
        self.assertTrue(response.data["detail"])

    # --- POST /payments --------------------------------------------------

    def test_manual_payment_rejected_while_invoice_locked(self, mailer):
        self.lock(self.invoice)
        for client in (self.parent, self.staff):
            response = self.create_manual(client)
            self.assertCode(response, 400, "INVOICE_LOCKED")
            self.assertIn("WIB", response.data["detail"])
            self.assertIn("Batalkan checkout", response.data["detail"])
        self.assertFalse(Payment.objects.filter(student_invoice=self.invoice).exists())
        mailer.assert_not_called()

    def test_other_invoices_of_the_student_stay_open(self, mailer):
        self.lock(self.invoice)
        self.assertEqual(self.create_manual(self.staff, self.invoice_2).status_code, 201)

    def test_released_checkout_does_not_lock(self, mailer):
        self.lock(self.invoice, status=GatewayPayment.Status.EXPIRED, is_active=False)
        response = self.create_manual(self.staff)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["payment_channel"], "manual")

    # --- PUT / PATCH / DELETE /payments/{id} ----------------------------

    def test_gateway_payment_row_is_read_only(self, mailer):
        payment = self.gateway_payment_row()
        url = f"/api/payments/{payment.id}/"
        self.assertCode(self.staff.patch(url, {"status": "rejected", "rejection_reason": "x"}, format="json"), 403, "GATEWAY_PAYMENT_READONLY")
        self.assertCode(self.staff.put(url, {
            "student_invoice_id": self.invoice.id, "amount": "50000.00", "payment_method": "cash",
        }, format="json"), 403, "GATEWAY_PAYMENT_READONLY")
        self.assertCode(self.admin.delete(url), 403, "GATEWAY_PAYMENT_READONLY")

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
        self.assertEqual(payment.payment_method, Payment.PaymentMethod.VIRTUAL_ACCOUNT)

    def test_gateway_payment_row_is_still_readable(self, mailer):
        payment = self.gateway_payment_row()
        response = self.parent.get(f"/api/payments/{payment.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["payment_channel"], "payment_gateway")
        self.assertEqual(response.data["gateway_payment_id"], payment.gateway_payment_id)
        self.assertEqual(response.data["payment_method"], "virtual_account")

    def test_resubmitting_rejected_payment_blocked_while_locked(self, mailer):
        payment = self.rejected_manual_payment()
        self.lock(self.invoice)
        response = self.staff.patch(f"/api/payments/{payment.id}/", {"status": "submitted"}, format="json")
        self.assertCode(response, 400, "INVOICE_LOCKED")
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REJECTED)

    def test_completing_rejected_payment_blocked_while_locked(self, mailer):
        payment = self.rejected_manual_payment()
        self.lock(self.invoice)
        response = self.staff.patch(f"/api/payments/{payment.id}/", {"status": "completed"}, format="json")
        self.assertCode(response, 400, "INVOICE_LOCKED")
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, StudentInvoice.Status.PAID)

    def test_manual_payment_delete_still_works(self, mailer):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=self.invoice.total_amount,
            payment_method=Payment.PaymentMethod.CASH,
        )
        self.assertEqual(self.admin.delete(f"/api/payments/{payment.id}/").status_code, 204)

    # --- /payment-proofs -------------------------------------------------

    def test_proof_upload_to_gateway_payment_rejected(self, mailer):
        payment = self.gateway_payment_row()
        response = self.parent.post("/api/payment-proofs/", {"payment_id": payment.id, "image_data": PROOF}, format="json")
        self.assertCode(response, 403, "GATEWAY_PAYMENT_READONLY")
        self.assertFalse(PaymentProof.objects.filter(payment=payment).exists())

    def test_proof_upload_to_rejected_payment_blocked_while_locked(self, mailer):
        payment = self.rejected_manual_payment()
        self.lock(self.invoice)
        response = self.parent.post("/api/payment-proofs/", {"payment_id": payment.id, "image_data": PROOF}, format="json")
        self.assertCode(response, 400, "INVOICE_LOCKED")
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REJECTED)
        self.assertFalse(PaymentProof.objects.filter(payment=payment).exists())

    def test_proof_upload_to_rejected_payment_allowed_when_unlocked(self, mailer):
        payment = self.rejected_manual_payment()
        response = self.parent.post("/api/payment-proofs/", {"payment_id": payment.id, "image_data": PROOF}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUBMITTED)

    def test_proofs_of_gateway_payment_cannot_be_changed(self, mailer):
        payment = self.gateway_payment_row()
        proof = PaymentProof.objects.create(payment=payment, image_data=PROOF)
        url = f"/api/payment-proofs/{proof.id}/"
        self.assertCode(self.staff.patch(url, {"image_data": PROOF}, format="json"), 403, "GATEWAY_PAYMENT_READONLY")
        self.assertCode(self.admin.delete(url), 403, "GATEWAY_PAYMENT_READONLY")
        self.assertTrue(PaymentProof.objects.filter(pk=proof.pk).exists())

    def test_proof_cannot_be_moved_to_gateway_payment(self, mailer):
        manual = Payment.objects.create(
            student_invoice=self.invoice_2, amount=self.invoice_2.total_amount,
            payment_method=Payment.PaymentMethod.CASH,
        )
        proof = PaymentProof.objects.create(payment=manual, image_data=PROOF)
        gateway_row = self.gateway_payment_row()
        response = self.staff.patch(f"/api/payment-proofs/{proof.id}/", {"payment_id": gateway_row.id}, format="json")
        self.assertCode(response, 403, "GATEWAY_PAYMENT_READONLY")
        proof.refresh_from_db()
        self.assertEqual(proof.payment_id, manual.id)

