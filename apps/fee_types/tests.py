from django.test import TestCase

from rest_framework.test import APIClient
from apps.users.models import User
from apps.locations.models import Location
from apps.schools.models import Branch, School
from .models import FeeType
from apps.fee_types.models import FeeTypeClass
from apps.classes.models import Class, ClassStudent
from apps.academic_years.models import AcademicYear
from apps.students.models import Student
from datetime import date
from decimal import Decimal

# Create your tests here.


class FeeTypeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = User.objects.create_user(
            email="fee-api@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        self.client.force_authenticate(user=user)
        location = Location.objects.create(name="Fee Province", code="FP", location_type="PROVINCE")
        school = School.objects.create(name="Fee School", register_number="FEE-001")
        self.branch = Branch.objects.create(school=school, name="Main", code="MAIN", location=location)
        year = AcademicYear.objects.create(
            branch=self.branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        self.class_obj = Class.objects.create(name="Grade 1", branch=self.branch, academic_year=year)
        self.student = Student.objects.create(
            first_name="Fee", last_name="Student", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active",
        )
        ClassStudent.objects.create(class_obj=self.class_obj, student=self.student, is_current=True)

    def test_create_fee_type(self):
        response = self.client.post(
            "/api/fee-types/",
            {"branch": self.branch.id, "name": "Tuition", "amount": "100000.00", "currency": "IDR"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Tuition")

    def test_filter_fee_types_by_branch_and_active_status(self):
        FeeType.objects.create(branch=self.branch, name="Active Fee", amount=100, is_active=True)
        FeeType.objects.create(branch=self.branch, name="Inactive Fee", amount=200, is_active=False)
        response = self.client.get(f"/api/fee-types/?branch_id={self.branch.id}&is_active=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Active Fee")

    def test_recurring_fee_requires_frequency(self):
        response = self.client.post(
            "/api/fee-types/",
            {
                "branch": self.branch.id,
                "name": "Monthly Fee",
                "amount": "100000.00",
                "is_recurring": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_generate_manual_invoices_for_fee_type(self):
        fee_type = FeeType.objects.create(
            branch=self.branch, name="Manual Tuition", amount=Decimal("100000"), is_recurring=False
        )
        FeeTypeClass.objects.create(fee_type=fee_type, class_obj=self.class_obj)
        response = self.client.post(
            f"/api/fee-types/{fee_type.id}/generate-invoices/",
            {"invoice_date": "2026-10-01", "due_date": "2026-10-31", "remark": "October tuition"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created_count"], 1)

    def test_manual_invoice_generation_is_idempotent(self):
        fee_type = FeeType.objects.create(
            branch=self.branch, name="Idempotent Tuition", amount=Decimal("100000"), is_recurring=False
        )
        FeeTypeClass.objects.create(fee_type=fee_type, class_obj=self.class_obj)
        payload = {"invoice_date": "2026-10-02"}
        first = self.client.post(f"/api/fee-types/{fee_type.id}/generate-invoices/", payload, format="json")
        second = self.client.post(f"/api/fee-types/{fee_type.id}/generate-invoices/", payload, format="json")
        self.assertEqual(first.data["created_count"], 1)
        self.assertEqual(second.data["created_count"], 0)

    def test_manual_invoice_rejects_due_date_before_invoice_date(self):
        fee_type = FeeType.objects.create(
            branch=self.branch, name="Invalid Dates", amount=Decimal("100000"), is_recurring=False
        )
        response = self.client.post(
            f"/api/fee-types/{fee_type.id}/generate-invoices/",
            {"invoice_date": "2026-10-10", "due_date": "2026-10-01"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_fee_type_retrieve_update_and_delete(self):
        fee_type = FeeType.objects.create(branch=self.branch, name="CRUD Fee", amount=100)
        detail = self.client.get(f"/api/fee-types/{fee_type.id}/")
        self.assertEqual(detail.status_code, 200)
        updated = self.client.patch(f"/api/fee-types/{fee_type.id}/", {"name": "Updated Fee"}, format="json")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["name"], "Updated Fee")
        deleted = self.client.delete(f"/api/fee-types/{fee_type.id}/")
        self.assertEqual(deleted.status_code, 204)

    def test_fee_type_assigns_classes_from_class_ids(self):
        response = self.client.post(
            "/api/fee-types/",
            {"branch": self.branch.id, "name": "Class Fee", "amount": "100", "class_ids": [self.class_obj.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["fee_type_classes"]), 1)
