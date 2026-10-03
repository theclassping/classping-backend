from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient
from datetime import date
from decimal import Decimal

from apps.payments.models import Payment
from apps.payments.views import PaymentViewSet
from apps.users.models import User
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.academic_years.models import AcademicYear
from apps.classes.models import Class, ClassStudent
from apps.students.models import Student
from apps.students.models import StudentGuardian
from apps.guardians.models import Guardian
from apps.fee_types.models import FeeType
from apps.student_invoices.models import StudentInvoice
from apps.staffs.models import Staff
from django.test import override_settings


class PaymentAuthorizationTests(SimpleTestCase):
    def test_non_staff_cannot_complete_payment_before_save(self):
        view = PaymentViewSet()
        view.request = SimpleNamespace(user=SimpleNamespace(staff=None))

        serializer = Mock()
        serializer.instance = Mock(status=Payment.Status.COMPLETED)
        serializer.validated_data = {"status": Payment.Status.COMPLETED}
        serializer.save.side_effect = AssertionError("save should not be called before staff verification")

        with self.assertRaises(PermissionDenied):
            view.perform_update(serializer)


class PaymentApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="parent-payment@example.com",
            password="StrongPassword123!",
            role=User.Role.PARENT,
        )
        self.staff_user = User.objects.create_user(
            email="staff-payment@example.com",
            password="StrongPassword123!",
            role=User.Role.STAFF,
        )
        self.admin_user = User.objects.create_user(
            email="admin-payment@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        location = Location.objects.create(name="Payment Province", code="PP", location_type="PROVINCE")
        school = School.objects.create(name="Payment School", register_number="PAY-001")
        branch = Branch.objects.create(school=school, name="Main", code="MAIN", location=location)
        academic_year = AcademicYear.objects.create(
            branch=branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        Staff.objects.create(
            user=self.staff_user, branch=branch, first_name="Payment", last_name="Staff",
            email="staff-payment@example.com", staff_type=Staff.StaffType.OFFICER,
            hire_date=date(2026, 7, 1), qualification="Finance",
        )
        class_obj = Class.objects.create(name="Grade 1", branch=branch, academic_year=academic_year)
        student = Student.objects.create(
            first_name="Test", last_name="Student", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active",
        )
        guardian_user = User.objects.create_user(
            email="guardian-payment@example.com",
            password="StrongPassword123!",
            role=User.Role.PARENT,
        )
        guardian = Guardian.objects.create(
            user=guardian_user,
            name="Payment Guardian",
            email="guardian-payment@example.com",
        )
        StudentGuardian.objects.create(
            student=student,
            guardian=guardian,
            relationship="father",
            is_primary=True,
        )
        class_student = ClassStudent.objects.create(class_obj=class_obj, student=student, is_current=True)
        fee_type = FeeType.objects.create(branch=branch, name="Tuition", amount=Decimal("100000"))
        self.invoice = StudentInvoice.objects.create(
            class_student=class_student, fee_type=fee_type, invoice_no="INV-PAY-001",
            invoice_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
            subtotal=Decimal("100000"), total_amount=Decimal("100000"), currency="IDR",
        )

    @patch("apps.payments.serializers.Mailer")
    def test_create_payment_marks_invoice_submitted(self, mailer):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post("/api/payments/", {
            "student_invoice_id": self.invoice.id,
            "amount": "100000.00",
            "payment_method": "bank_transfer",
            "status": "submitted",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAYMENT_SUBMITTED)

    @patch("apps.payments.serializers.Mailer")
    def test_payment_amount_must_match_invoice_total(self, mailer):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post("/api/payments/", {
            "student_invoice_id": self.invoice.id,
            "amount": "1.00",
            "payment_method": "cash",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    @patch("apps.payments.serializers.Mailer")
    def test_staff_can_complete_payment_and_mark_invoice_paid(self, mailer):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("100000"),
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
        )
        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        response = client.patch(f"/api/payments/{payment.id}/", {"status": "completed"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAID)

    @patch("apps.payments.serializers.Mailer")
    def test_staff_can_reject_payment_and_mark_invoice_unpaid(self, mailer):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("100000"),
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
        )
        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        response = client.patch(
            f"/api/payments/{payment.id}/",
            {"status": "rejected", "rejection_reason": "Unreadable proof"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REJECTED)
        self.assertEqual(self.invoice.status, StudentInvoice.Status.UNPAID)

    @patch("apps.payments.serializers.Mailer")
    @override_settings(MAILJET_TEMPLATES={"payment_rejected": 303})
    def test_rejection_sends_correct_mailer_template_and_payload(self, mailer):
        payment = Payment.objects.create(student_invoice=self.invoice, amount=Decimal("100000"), payment_method=Payment.PaymentMethod.BANK_TRANSFER)
        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        response = client.patch(f"/api/payments/{payment.id}/", {"status": "rejected", "rejection_reason": "Bad proof"}, format="json")
        self.assertEqual(response.status_code, 200)
        mailer.return_value.send_template.assert_called_once()
        kwargs = mailer.return_value.send_template.call_args.kwargs
        self.assertEqual(kwargs["template_id"], 303)
        self.assertEqual(kwargs["variables"]["status"], "rejected")
        self.assertEqual(kwargs["variables"]["rejection_reason"], "Bad proof")
        self.assertEqual(kwargs["variables"]["amount"], "100000.00")
        self.assertEqual(kwargs["variables"]["name"], "Payment Guardian")
        self.assertNotIn("T", kwargs["variables"]["updated_at"])
        self.assertEqual(kwargs["variables"]["due_date"], "31 July 2026")

    @patch("apps.payments.serializers.Mailer")
    def test_invalid_status_and_full_put_behavior(self, mailer):
        payment = Payment.objects.create(student_invoice=self.invoice, amount=Decimal("100000"), payment_method=Payment.PaymentMethod.CASH)
        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        invalid = client.patch(f"/api/payments/{payment.id}/", {"status": "cancelled"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        put = client.put(f"/api/payments/{payment.id}/", {
            "student_invoice_id": self.invoice.id, "amount": "100000.00",
            "payment_method": "bank_transfer", "status": "submitted",
        }, format="json")
        self.assertEqual(put.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_method, Payment.PaymentMethod.BANK_TRANSFER)

    def test_admin_can_delete_payment_proof(self):
        from apps.payments.models import PaymentProof
        payment = Payment.objects.create(student_invoice=self.invoice, amount=Decimal("100000"), payment_method=Payment.PaymentMethod.BANK_TRANSFER)
        proof = PaymentProof.objects.create(payment=payment, image_data={"object_key": "proofs/admin.jpg"})
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        response = client.delete(f"/api/payment-proofs/{proof.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(PaymentProof.objects.filter(pk=proof.id).exists())

    def test_rejection_requires_reason(self):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("100000"),
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
        )
        client = APIClient()
        client.force_authenticate(user=self.staff_user)
        response = client.patch(
            f"/api/payments/{payment.id}/", {"status": "rejected"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_payment_rejects_zero_amount(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            "/api/payments/",
            {
                "student_invoice_id": self.invoice.id,
                "amount": "0.00",
                "payment_method": "cash",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_parent_cannot_delete_payment_but_admin_can(self):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("100000"),
            payment_method=Payment.PaymentMethod.CASH,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        self.assertEqual(client.delete(f"/api/payments/{payment.id}/").status_code, 403)
        client.force_authenticate(user=self.admin_user)
        self.assertEqual(client.delete(f"/api/payments/{payment.id}/").status_code, 204)

    @patch("apps.payments.serializers.Mailer")
    def test_payment_proof_crud(self, mailer):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("100000"),
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        create = client.post(
            "/api/payment-proofs/",
            {"payment_id": payment.id, "image_data": {"object_key": "proofs/one.jpg"}},
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        proof_id = create.data["id"]
        self.assertEqual(client.get("/api/payment-proofs/").status_code, 200)
        parent_update = client.patch(
            f"/api/payment-proofs/{proof_id}/",
            {"image_data": {"object_key": "proofs/two.jpg"}},
            format="json",
        )
        self.assertEqual(parent_update.status_code, 403)
        client.force_authenticate(user=self.staff_user)
        update = client.patch(
            f"/api/payment-proofs/{proof_id}/",
            {"image_data": {"object_key": "proofs/two.jpg"}},
            format="json",
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(client.delete(f"/api/payment-proofs/{proof_id}/").status_code, 403)

    @patch("apps.payments.serializers.Mailer")
    def test_new_proof_resubmits_rejected_payment(self, mailer):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("100000"),
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
            status=Payment.Status.REJECTED,
            rejection_reason="Old proof rejected",
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            "/api/payment-proofs/",
            {"payment_id": payment.id, "image_data": {"object_key": "proofs/retry.jpg"}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        payment.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUBMITTED)
        self.assertEqual(self.invoice.status, StudentInvoice.Status.PAYMENT_SUBMITTED)
