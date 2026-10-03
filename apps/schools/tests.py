from django.test import TestCase

from datetime import date
from rest_framework.test import APIClient
from apps.users.models import User
from apps.locations.models import Location
from .models import School, Branch


class SchoolBranchCrudApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        admin = User.objects.create_user(email="school-admin@example.com", password="StrongPassword123!", role=User.Role.ADMIN)
        self.client.force_authenticate(user=admin)
        self.location = Location.objects.create(name="School Province", code="SP", location_type="PROVINCE")

    def test_school_crud(self):
        create = self.client.post("/api/schools/", {"name": "School A", "register_number": "SCH-A"}, format="json")
        self.assertEqual(create.status_code, 201)
        school_id = create.data["id"]
        self.assertEqual(self.client.get(f"/api/schools/{school_id}/").status_code, 200)
        update = self.client.patch(f"/api/schools/{school_id}/", {"name": "School Updated"}, format="json")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/schools/{school_id}/").status_code, 204)

    def test_duplicate_school_register_number_fails(self):
        School.objects.create(name="Existing", register_number="DUP-001")
        response = self.client.post("/api/schools/", {"name": "Duplicate", "register_number": "DUP-001"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_branch_crud_and_invalid_school(self):
        school = School.objects.create(name="Branch School", register_number="BR-001")
        create = self.client.post("/api/branches/", {"school": school.id, "name": "Main", "code": "MAIN", "location_id": self.location.id}, format="json")
        self.assertEqual(create.status_code, 201)
        branch_id = create.data["id"]
        self.assertEqual(self.client.patch(f"/api/branches/{branch_id}/", {"name": "Updated"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/branches/{branch_id}/").status_code, 204)
        invalid = self.client.post("/api/branches/", {"school": 999999, "name": "Bad", "code": "BAD", "location_id": self.location.id}, format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_duplicate_branch_code_per_school_fails(self):
        school = School.objects.create(name="Duplicate Branch School", register_number="BR-002")
        Branch.objects.create(school=school, name="Existing", code="SAME", location=self.location)
        response = self.client.post("/api/branches/", {"school": school.id, "name": "Duplicate", "code": "SAME", "location_id": self.location.id}, format="json")
        self.assertEqual(response.status_code, 400)

# Create your tests here.
