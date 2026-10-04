from django.test import TestCase

from datetime import date
from rest_framework.test import APIClient
from apps.users.models import User
from apps.locations.models import Location
from apps.schools.models import School, Branch
from .models import Staff


class StaffCrudApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="staff-admin@example.com", password="StrongPassword123!", role=User.Role.ADMIN)
        self.staff_user = User.objects.create_user(email="staff-crud@example.com", password="StrongPassword123!", role=User.Role.STAFF)
        self.teacher_user = User.objects.create_user(email="teacher-crud@example.com", password="StrongPassword123!", role=User.Role.TEACHER)
        self.client.force_authenticate(user=self.admin)
        location = Location.objects.create(name="Staff Province", code="ST", location_type="PROVINCE")
        school = School.objects.create(name="Staff School", register_number="ST-001")
        self.branch = Branch.objects.create(school=school, name="Main", code="MAIN", location=location)

    def test_staff_crud(self):
        payload = {"branch": self.branch.id, "user": self.staff_user.id, "first_name": "Staff", "last_name": "One", "email": self.staff_user.email, "staff_type": "officer", "hire_date": "2026-07-01", "qualification": "Finance"}
        create = self.client.post("/api/staffs/", payload, format="json")
        self.assertEqual(create.status_code, 201)
        staff_id = create.data["id"]
        self.assertEqual(self.client.get(f"/api/staffs/{staff_id}/").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/staffs/{staff_id}/", {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/staffs/{staff_id}/").status_code, 204)

    def test_teacher_staff_requires_teacher_role(self):
        payload = {"branch": self.branch.id, "user": self.staff_user.id, "first_name": "Bad", "last_name": "Teacher", "email": "bad-teacher@example.com", "staff_type": "teacher", "hire_date": "2026-07-01", "qualification": "Education"}
        response = self.client.post("/api/staffs/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_staff_creation_generates_linked_user(self):
        payload = {
            "branch": self.branch.id,
            "first_name": "New",
            "last_name": "Teacher",
            "email": "new-teacher@example.com",
            "staff_type": "teacher",
            "hire_date": "2026-07-01",
            "qualification": "Education",
        }

        response = self.client.post("/api/staffs/", payload, format="json")

        self.assertEqual(response.status_code, 201)
        staff = Staff.objects.get(pk=response.data["id"])
        self.assertIsNotNone(staff.user)
        self.assertEqual(staff.user.email, payload["email"])
        self.assertEqual(staff.user.role, User.Role.TEACHER)
        self.assertTrue(staff.user.has_usable_password())

    def test_staff_creation_rejects_existing_user_email_without_user_id(self):
        payload = {
            "branch": self.branch.id,
            "first_name": "Existing",
            "last_name": "Account",
            "email": self.staff_user.email,
            "staff_type": "officer",
            "hire_date": "2026-07-01",
            "qualification": "Operations",
        }

        response = self.client.post("/api/staffs/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

# Create your tests here.
