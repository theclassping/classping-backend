from django.test import TestCase
from datetime import date, timedelta
from decimal import Decimal

from rest_framework.test import APIClient

from apps.users.models import User
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.academic_years.models import AcademicYear
from apps.classes.models import Class, ClassStudent
from apps.students.models import Student
from apps.fee_types.models import FeeType
from .models import StudentInvoice
from apps.fee_types.models import FeeTypeClass
from apps.student_invoices.services import generate_recurring_invoices
from apps.student_invoices.scheduler import SCHEDULED_JOBS, register_jobs
from django.core.management import call_command
from io import StringIO
from unittest.mock import Mock

# Create your tests here.


class StudentInvoiceApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = User.objects.create_user(
            email="invoice-api@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        self.client.force_authenticate(user=user)
        location = Location.objects.create(name="Invoice Province", code="IP", location_type="PROVINCE")
        school = School.objects.create(name="Invoice School", register_number="INV-001")
        branch = Branch.objects.create(school=school, name="Main", code="MAIN", location=location)
        year = AcademicYear.objects.create(
            branch=branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        class_obj = Class.objects.create(name="Grade 1", branch=branch, academic_year=year)
        student = Student.objects.create(
            first_name="Invoice", last_name="Student", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active",
        )
        class_student = ClassStudent.objects.create(class_obj=class_obj, student=student, is_current=True)
        fee_type = FeeType.objects.create(branch=branch, name="Tuition", amount=Decimal("100000"))
        today = date.today()
        self.overdue = StudentInvoice.objects.create(
            class_student=class_student, fee_type=fee_type, invoice_no="INV-OVERDUE",
            invoice_date=today - timedelta(days=60), due_date=today - timedelta(days=30),
            subtotal=Decimal("100000"), total_amount=Decimal("100000"), status=StudentInvoice.Status.UNPAID,
        )
        self.current = StudentInvoice.objects.create(
            class_student=class_student, fee_type=fee_type, invoice_no="INV-CURRENT",
            invoice_date=today, due_date=today + timedelta(days=30),
            subtotal=Decimal("100000"), total_amount=Decimal("100000"), status=StudentInvoice.Status.UNPAID,
        )

    def test_list_invoices(self):
        response = self.client.get("/api/student-invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_filter_overdue_invoices(self):
        response = self.client.get("/api/student-invoices/?is_overdue=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["invoice_no"], "INV-OVERDUE")

    def test_retrieve_invoice_detail(self):
        response = self.client.get(f"/api/student-invoices/{self.current.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["invoice_no"], "INV-CURRENT")
        self.assertIn("payment", response.data)

    def test_recurring_service_generates_invoice_for_current_student(self):
        recurring = FeeType.objects.create(
            branch=self.overdue.fee_type.branch,
            name="Monthly Tuition",
            amount=Decimal("75000"),
            is_recurring=True,
            recurring_frequency=FeeType.RecurringFrequency.MONTHLY,
        )
        FeeTypeClass.objects.create(fee_type=recurring, class_obj=self.overdue.class_student.class_obj)
        count = generate_recurring_invoices(date(2026, 10, 15))
        self.assertEqual(count, 1)

    def test_recurring_service_does_not_duplicate_invoice(self):
        recurring = FeeType.objects.create(
            branch=self.overdue.fee_type.branch,
            name="Quarterly Tuition",
            amount=Decimal("75000"),
            is_recurring=True,
            recurring_frequency=FeeType.RecurringFrequency.QUARTERLY,
        )
        FeeTypeClass.objects.create(fee_type=recurring, class_obj=self.overdue.class_student.class_obj)
        self.assertEqual(generate_recurring_invoices(date(2026, 10, 15)), 1)
        self.assertEqual(generate_recurring_invoices(date(2026, 10, 15)), 0)

    def test_mark_overdue_command_updates_only_unpaid_past_due_invoices(self):
        output = StringIO()
        call_command("mark_overdue_invoices", stdout=output)
        self.overdue.refresh_from_db()
        self.current.refresh_from_db()
        self.assertEqual(self.overdue.status, StudentInvoice.Status.OVERDUE)
        self.assertEqual(self.current.status, StudentInvoice.Status.UNPAID)
        self.assertIn("Marked 1 invoice(s) as overdue", output.getvalue())

    def test_reminder_command_reports_only_invoices_due_in_five_days(self):
        reminder_fee = FeeType.objects.create(
            branch=self.current.fee_type.branch,
            name="Reminder Fee",
            amount=Decimal("100000"),
        )
        reminder = StudentInvoice.objects.create(
            class_student=self.current.class_student,
            fee_type=reminder_fee,
            invoice_no="INV-REMINDER",
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=5),
            subtotal=Decimal("100000"), total_amount=Decimal("100000"),
            status=StudentInvoice.Status.UNPAID,
        )
        output = StringIO()
        call_command("send_invoice_reminders", stdout=output)
        self.assertIn(reminder.invoice_no, output.getvalue())

    def test_scheduler_registers_all_invoice_jobs(self):
        scheduler = Mock()
        register_jobs(scheduler)
        self.assertEqual(scheduler.add_job.call_count, len(SCHEDULED_JOBS))

    def test_invoice_filters_by_student_status_and_fee_type(self):
        response = self.client.get(
            f"/api/student-invoices/?student_id={self.current.class_student.student_id}"
            f"&status=unpaid&fee_type_id={self.current.fee_type_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_invoice_filter_by_payment_status(self):
        from apps.payments.models import Payment
        Payment.objects.create(
            student_invoice=self.current,
            amount=self.current.total_amount,
            payment_method=Payment.PaymentMethod.BANK_TRANSFER,
            status=Payment.Status.SUBMITTED,
        )
        response = self.client.get("/api/student-invoices/?payment_status=submitted")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_invoice_update_and_delete(self):
        updated = self.client.patch(
            f"/api/student-invoices/{self.current.id}/",
            {"remark": "Updated remark"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        deleted = self.client.delete(f"/api/student-invoices/{self.current.id}/")
        self.assertEqual(deleted.status_code, 204)
