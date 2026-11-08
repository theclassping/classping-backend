from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.academic_years.models import AcademicYear
from apps.classes.models import Class, ClassStudent
from apps.core.access import scope_queryset
from apps.fee_types.models import FeeType
from apps.guardians.models import Guardian
from apps.locations.models import Location
from apps.payments.models import Payment
from apps.schools.models import Branch, School
from apps.staffs.models import Staff
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student, StudentGuardian
from apps.users.models import User

from .models import GatewayPayment, GatewayPaymentItem

PASSWORD = "StrongPassword123!"


class NoMailjetMixin:
    """For TransactionTestCase: it really commits, so on_commit emails
    (welcome email, payment_completed) would call Mailjet. Put first in the
    bases."""

    def setUp(self):
        patcher = mock.patch("apps.mailer.services.Client")
        patcher.start().return_value.send.create.return_value.status_code = 200
        self.addCleanup(patcher.stop)
        super().setUp()


def make_branch(school, location, code):
    return Branch.objects.create(school=school, name=code, code=code, location=location)


def make_staff(branch, email, staff_type, role=User.Role.STAFF):
    user = User.objects.create_user(email=email, password=PASSWORD, role=role)
    Staff.objects.create(
        user=user, branch=branch, first_name="S", last_name=staff_type,
        email=email, staff_type=staff_type, hire_date=date(2026, 7, 1), qualification="-",
    )
    return user


def make_parent(email, name):
    user = User.objects.create_user(email=email, password=PASSWORD, role=User.Role.PARENT)
    return user, Guardian.objects.create(user=user, name=name, email=email)


class GatewayFixtureMixin:
    def setUp(self):
        location = Location.objects.create(name="GW Province", code="GWP", location_type="PROVINCE")
        school = School.objects.create(name="GW School", register_number="GW-001")
        self.branch = make_branch(school, location, "GW-A")
        self.other_branch = make_branch(school, location, "GW-B")

        academic_year = AcademicYear.objects.create(
            branch=self.branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        class_obj = Class.objects.create(name="Grade 1", branch=self.branch, academic_year=academic_year)
        self.student = Student.objects.create(
            first_name="Budi", last_name="Santoso", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active", branch=self.branch,
        )
        self.parent_user, self.guardian = make_parent("gw-parent@example.com", "Ibu Sari")
        self.second_parent_user, self.second_guardian = make_parent("gw-parent2@example.com", "Pak Budi")
        self.other_parent_user, _ = make_parent("gw-other@example.com", "Other Parent")
        StudentGuardian.objects.create(student=self.student, guardian=self.guardian, relationship="mother", is_primary=True)
        StudentGuardian.objects.create(student=self.student, guardian=self.second_guardian, relationship="father", is_primary=False)

        self.staff_user = make_staff(self.branch, "gw-officer@example.com", Staff.StaffType.OFFICER)
        self.other_branch_staff = make_staff(self.other_branch, "gw-officer-b@example.com", Staff.StaffType.OFFICER)
        self.teacher_user = make_staff(self.branch, "gw-teacher@example.com", Staff.StaffType.TEACHER, role=User.Role.TEACHER)

        class_student = ClassStudent.objects.create(class_obj=class_obj, student=self.student, is_current=True)
        fee_type = FeeType.objects.create(branch=self.branch, name="SPP", amount=Decimal("50000"))
        outing = FeeType.objects.create(branch=self.branch, name="Outing", amount=Decimal("75000"))
        self.invoice = StudentInvoice.objects.create(
            class_student=class_student, fee_type=fee_type, invoice_no="INV-GW-001",
            invoice_date=date(2026, 11, 1), due_date=date(2026, 11, 30),
            subtotal=Decimal("50000"), total_amount=Decimal("50000"),
        )
        self.invoice_2 = StudentInvoice.objects.create(
            class_student=class_student, fee_type=outing, invoice_no="INV-GW-002",
            invoice_date=date(2026, 11, 1), due_date=date(2026, 11, 30),
            subtotal=Decimal("75000"), total_amount=Decimal("75000"),
        )

    def make_payment(self, payment_no="PAY-1", idempotency_key="key-1", guardian=None, **overrides):
        values = dict(
            payment_no=payment_no,
            branch=self.branch,
            student=self.student,
            guardian=guardian or self.guardian,
            provider="rintisan",
            channel_code="VABCA",
            payment_method=Payment.PaymentMethod.VIRTUAL_ACCOUNT,
            invoice_total=Decimal("125000"),
            transaction_fee=Decimal("5000"),
            amount=Decimal("130000"),
            idempotency_key=idempotency_key,
            deadline_date=date(2026, 11, 8),
            expires_at=datetime(2026, 11, 8, 16, 59, 59, tzinfo=timezone.utc),
        )
        values.update(overrides)
        return GatewayPayment.objects.create(**values)

    def add_item(self, payment, invoice, is_active=True):
        return GatewayPaymentItem.objects.create(
            gateway_payment=payment, student_invoice=invoice,
            amount=invoice.total_amount, is_active=is_active,
        )


class GatewayPaymentConstraintTests(GatewayFixtureMixin, TestCase):
    def assertIntegrityError(self, func):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                func()

    def test_checkout_can_hold_several_invoices_of_one_student(self):
        payment = self.make_payment()
        self.add_item(payment, self.invoice)
        self.add_item(payment, self.invoice_2)
        self.assertEqual(payment.items.count(), 2)

    def test_invoice_cannot_be_in_two_active_checkouts(self):
        first = self.make_payment("PAY-1", "key-1")
        self.add_item(first, self.invoice)
        second = self.make_payment("PAY-2", "key-2")
        self.assertIntegrityError(lambda: self.add_item(second, self.invoice))

    def test_inactive_item_releases_the_invoice(self):
        first = self.make_payment("PAY-1", "key-1", status=GatewayPayment.Status.EXPIRED)
        self.add_item(first, self.invoice, is_active=False)
        second = self.make_payment("PAY-2", "key-2")
        self.add_item(second, self.invoice)
        self.assertEqual(GatewayPaymentItem.objects.filter(student_invoice=self.invoice).count(), 2)

    def test_same_invoice_twice_in_one_checkout_rejected(self):
        payment = self.make_payment()
        self.add_item(payment, self.invoice, is_active=False)
        self.assertIntegrityError(lambda: self.add_item(payment, self.invoice, is_active=False))

    def test_idempotency_key_unique_per_guardian(self):
        self.make_payment("PAY-1", "same-key")
        self.assertIntegrityError(lambda: self.make_payment("PAY-2", "same-key"))
        # Another guardian may reuse the same key.
        self.make_payment("PAY-3", "same-key", guardian=self.second_guardian)

    def test_payment_no_unique(self):
        self.make_payment("PAY-1", "key-1")
        self.assertIntegrityError(lambda: self.make_payment("PAY-1", "key-2"))

    def test_amount_must_equal_invoice_total_plus_fee(self):
        self.assertIntegrityError(lambda: self.make_payment(amount=Decimal("125000")))

    def test_amounts_must_be_valid(self):
        self.assertIntegrityError(
            lambda: self.make_payment(invoice_total=Decimal("0"), transaction_fee=Decimal("0"), amount=Decimal("0"))
        )
        self.assertIntegrityError(
            lambda: self.make_payment(transaction_fee=Decimal("-1"), amount=Decimal("124999"))
        )

    def test_new_payment_rows_default_to_manual(self):
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("50000"),
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
        )
        self.assertEqual(payment.payment_channel, Payment.PaymentChannel.MANUAL)
        self.assertIsNone(payment.gateway_payment_id)

    def test_payment_channel_must_match_gateway_payment(self):
        checkout = self.make_payment()
        self.assertIntegrityError(
            lambda: Payment.objects.create(
                student_invoice=self.invoice, amount=Decimal("50000"),
                payment_method=Payment.PaymentMethod.VIRTUAL_ACCOUNT,
                payment_channel=Payment.PaymentChannel.PAYMENT_GATEWAY,
            )
        )
        self.assertIntegrityError(
            lambda: Payment.objects.create(
                student_invoice=self.invoice, amount=Decimal("50000"),
                payment_method=Payment.PaymentMethod.BANK_TRANSFER,
                gateway_payment=checkout,
            )
        )
        payment = Payment.objects.create(
            student_invoice=self.invoice, amount=Decimal("50000"),
            payment_method=Payment.PaymentMethod.VIRTUAL_ACCOUNT,
            payment_channel=Payment.PaymentChannel.PAYMENT_GATEWAY,
            gateway_payment=checkout,
            status=Payment.Status.COMPLETED,
        )
        self.assertEqual(list(checkout.payments.all()), [payment])

    def test_branch_gateway_disabled_by_default(self):
        self.assertFalse(self.branch.is_payment_gateway_enabled)


class GatewayPaymentScopingTests(GatewayFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.payment = self.make_payment()
        self.item = self.add_item(self.payment, self.invoice)

    def visible(self, model, user):
        return list(scope_queryset(model.objects.all(), user))

    def test_every_guardian_of_the_student_sees_the_checkout(self):
        for user in (self.parent_user, self.second_parent_user):
            self.assertEqual(self.visible(GatewayPayment, user), [self.payment])
            self.assertEqual(self.visible(GatewayPaymentItem, user), [self.item])

    def test_other_parent_sees_nothing(self):
        self.assertEqual(self.visible(GatewayPayment, self.other_parent_user), [])
        self.assertEqual(self.visible(GatewayPaymentItem, self.other_parent_user), [])

    def test_staff_sees_only_own_branch(self):
        self.assertEqual(self.visible(GatewayPayment, self.staff_user), [self.payment])
        self.assertEqual(self.visible(GatewayPaymentItem, self.staff_user), [self.item])
        self.assertEqual(self.visible(GatewayPayment, self.other_branch_staff), [])
        self.assertEqual(self.visible(GatewayPaymentItem, self.other_branch_staff), [])

    def test_teacher_sees_nothing(self):
        self.assertEqual(self.visible(GatewayPayment, self.teacher_user), [])
        self.assertEqual(self.visible(GatewayPaymentItem, self.teacher_user), [])
