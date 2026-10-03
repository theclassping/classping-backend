from django.test import TestCase

from rest_framework.test import APIClient
from apps.users.models import User
from .models import Guardian


class GuardianCrudApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(email="guardian-admin@example.com", password="StrongPassword123!", role=User.Role.ADMIN)
        self.parent = User.objects.create_user(email="guardian-parent@example.com", password="StrongPassword123!", role=User.Role.PARENT)
        self.staff = User.objects.create_user(email="guardian-staff@example.com", password="StrongPassword123!", role=User.Role.STAFF)
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

# Create your tests here.
