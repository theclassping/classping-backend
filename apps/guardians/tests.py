from django.test import TestCase

from rest_framework.test import APIClient
from apps.users.models import User
from .models import Guardian
from apps.students.models import Student, StudentGuardian


class GuardianCrudApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="guardian-admin@example.com", password="StrongPassword123!", role=User.Role.ADMIN)
        self.parent = User.objects.create_user(email="guardian-parent@example.com", password="StrongPassword123!", role=User.Role.PARENT)
        self.staff = User.objects.create_user(email="guardian-staff@example.com", password="StrongPassword123!", role=User.Role.STAFF)
        self.student = Student.objects.create(
            first_name="Student",
            last_name="One",
            date_of_birth="2015-01-01",
            gender="female",
            enroll_date="2025-01-01",
        )
        self.client.force_authenticate(user=self.admin)

    def test_guardian_crud(self):
        create = self.client.post("/api/guardians/", {"user_id": self.parent.id, "name": "Guardian One", "email": self.parent.email}, format="json")
        self.assertEqual(create.status_code, 201)
        guardian_id = create.data["id"]
        self.assertEqual(self.client.get(f"/api/guardians/{guardian_id}/").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/guardians/{guardian_id}/", {"name": "Updated Guardian"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/guardians/{guardian_id}/").status_code, 204)

    def test_guardian_rejects_non_parent_user(self):
        response = self.client.post("/api/guardians/", {"user_id": self.staff.id, "name": "Invalid", "email": self.staff.email}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_guardian_can_create_student_guardian_relation(self):
        response = self.client.post(
            "/api/guardians/",
            {
                "user_id": self.parent.id,
                "name": "Guardian One",
                "email": self.parent.email,
                "student_guardians": [{
                    "student_id": self.student.id,
                    "relationship": "father",
                    "is_primary": True,
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["student_guardians"]), 1)
        self.assertEqual(response.data["student_guardians"][0]["student_id"], self.student.id)
        self.assertTrue(response.data["student_guardians"][0]["is_primary"])

    def test_guardian_can_update_relation_fields(self):
        guardian = Guardian.objects.create(user=self.parent, name="Guardian One")
        relation = StudentGuardian.objects.create(
            guardian=guardian,
            student=self.student,
            relationship="father",
            is_primary=False,
        )

        response = self.client.patch(
            f"/api/guardians/{guardian.id}/",
            {"student_guardians": [{
                "id": relation.id,
                "student_id": self.student.id,
                "relationship": "mother",
                "is_primary": True,
            }]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        relation.refresh_from_db()
        self.assertEqual(relation.relationship, "mother")
        self.assertTrue(relation.is_primary)

# Create your tests here.
