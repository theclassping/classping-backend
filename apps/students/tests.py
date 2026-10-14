from django.test import TestCase

# Create your tests here.
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.guardians.models import Guardian
from apps.students.models import Student, StudentGuardian
from apps.classes.models import Class, ClassStudent
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.academic_years.models import AcademicYear


class StudentGuardianRequirementTests(TestCase):
    def _existing_guardian_student(self):
        student = Student.objects.create(
            first_name="Original", last_name="Student", date_of_birth="2022-01-08",
            gender="male", enroll_date="2026-10-14", status="active",
        )
        link = StudentGuardian.objects.create(
            student=student, guardian=self.guardian, relationship="father", is_primary=True,
        )
        return student, link

    def test_patch_updates_existing_guardian_and_user(self):
        student, link = self._existing_guardian_student()
        response = self.client.patch(f"/api/students/{student.pk}/", {
            "student_guardians": [{
                "id": link.pk, "guardian_id": self.guardian.pk,
                "relationship": "mother", "is_primary": True,
                "user": {
                    "first_name": "Guardian", "last_name": "Updated",
                    "email": "updated-guardian@example.com", "phone_number": "032654",
                },
            }],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.guardian.refresh_from_db()
        user = User.objects.get(pk=self.guardian.user_id)
        self.assertEqual(user.first_name, "Guardian")
        self.assertEqual(user.last_name, "Updated")
        self.assertEqual(user.email, "updated-guardian@example.com")
        self.assertEqual(self.guardian.email, user.email)
        self.assertEqual(self.guardian.name, "Guardian Updated")
        self.assertEqual(self.guardian.phone_number, "032654")
        link.refresh_from_db()
        self.assertEqual(link.relationship, "mother")
        # PATCH may change one nested field without overwriting the rest.
        response = self.client.patch(f"/api/students/{student.pk}/", {
            "student_guardians": [{"id": link.pk, "user": {"phone_number": "999"}}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.guardian.refresh_from_db()
        self.assertEqual(self.guardian.phone_number, "999")
        self.assertEqual(self.guardian.name, "Guardian Updated")

    def test_patch_duplicate_guardian_email_rolls_back_student(self):
        student, link = self._existing_guardian_student()
        original_email = self.guardian.user.email
        response = self.client.patch(f"/api/students/{student.pk}/", {
            "first_name": "Changed",
            "student_guardians": [{
                "id": link.pk, "user": {"email": self.user.email.upper()},
            }],
        }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("email", response.data["student_guardians"]["user"])
        student.refresh_from_db()
        self.assertEqual(student.first_name, "Original")
        self.assertEqual(User.objects.get(pk=self.guardian.user_id).email, original_email)

    def setUp(self):
        self.user = User.objects.create_user(
            email="student-api@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        guardian_user = User.objects.create_user(
            email="student-guardian@example.com",
            password="StrongPassword123!",
            role=User.Role.PARENT,
        )
        self.guardian = Guardian.objects.create(
            user=guardian_user,
            name="Student Guardian",
            email="student-guardian@example.com",
        )

    def _student_payload(self, guardians):
        return {
            "first_name": "Test",
            "last_name": "Student",
            "date_of_birth": "2018-01-01",
            "gender": "male",
            "enroll_date": "2026-07-01",
            "student_guardians": guardians,
        }

    def test_student_creation_fails_without_guardian(self):
        response = self.client.post(
            "/api/students/",
            self._student_payload([]),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("student_guardians", response.data)

    def test_student_creation_fails_without_primary_guardian(self):
        response = self.client.post(
            "/api/students/",
            self._student_payload([{
                "guardian_id": self.guardian.id,
                "relationship": "father",
                "is_primary": False,
            }]),
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_student_creation_succeeds_with_primary_guardian(self):
        response = self.client.post(
            "/api/students/",
            self._student_payload([{
                "guardian_id": self.guardian.id,
                "relationship": "father",
                "is_primary": True,
            }]),
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_student_detail_includes_nested_guardian(self):
        response = self.client.post(
            "/api/students/",
            self._student_payload([{
                "guardian_id": self.guardian.id,
                "relationship": "father",
                "is_primary": True,
            }]),
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        detail = self.client.get(f"/api/students/{response.data['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["student_guardians"]), 1)
        self.assertTrue(detail.data["student_guardians"][0]["is_primary"])

    def test_student_guardian_endpoint_can_create_and_list_link(self):
        student = Student.objects.create(
            first_name="Existing",
            last_name="Student",
            date_of_birth="2018-01-01",
            gender="male",
            enroll_date="2026-07-01",
            status="active",
        )
        create = self.client.post(
            "/api/student-guardians/",
            {
                "student_id": student.id,
                "guardian_id": self.guardian.id,
                "relationship": "father",
                "is_primary": True,
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201)

        listing = self.client.get("/api/student-guardians/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 1)

    def test_student_full_update_and_delete(self):
        response = self.client.post("/api/students/", self._student_payload([{
            "guardian_id": self.guardian.id, "relationship": "father", "is_primary": True,
        }]), format="json")
        student_id = response.data["id"]

        update = self.client.put(f"/api/students/{student_id}/", {
            **self._student_payload([{
                "id": StudentGuardian.objects.get(student_id=student_id).id,
                "guardian_id": self.guardian.id, "relationship": "father", "is_primary": True,
            }]),
            "nickname": "Updated",
        }, format="json")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data["nickname"], "Updated")

        delete = self.client.delete(f"/api/students/{student_id}/")
        self.assertEqual(delete.status_code, 204)
        self.assertFalse(Student.objects.filter(pk=student_id).exists())

    def test_student_guardian_removal_and_class_assignment_removal(self):
        student = Student.objects.create(
            first_name="Nested", last_name="Student", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active",
        )
        link = StudentGuardian.objects.create(
            student=student, guardian=self.guardian, relationship="father", is_primary=True,
        )
        location = Location.objects.create(name="Student Province", code="SP", location_type="PROVINCE")
        school = School.objects.create(name="Student School", register_number="STU-001")
        branch = Branch.objects.create(school=school, name="Main", code="STU-MAIN", location=location)
        year = AcademicYear.objects.create(branch=branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30))
        class_obj = Class.objects.create(name="Grade 1", branch=branch, academic_year=year)
        assignment = ClassStudent.objects.create(student=student, class_obj=class_obj, is_current=True)

        update = self.client.patch(f"/api/students/{student.id}/", {
            "student_guardians": [{"id": link.id, "_destroy": True}],
            "class_students": [{"id": assignment.id, "_destroy": True}],
        }, format="json")
        self.assertEqual(update.status_code, 200)
        self.assertFalse(StudentGuardian.objects.filter(pk=link.id).exists())
        self.assertFalse(ClassStudent.objects.filter(pk=assignment.id).exists())

    def test_student_class_assignment_can_be_updated(self):
        student = Student.objects.create(
            first_name="Assigned", last_name="Student", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active",
        )
        location = Location.objects.create(name="Assign Province", code="AP", location_type="PROVINCE")
        school = School.objects.create(name="Assign School", register_number="ASSIGN-001")
        branch = Branch.objects.create(school=school, name="Main", code="ASSIGN-MAIN", location=location)
        year = AcademicYear.objects.create(branch=branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30))
        class_obj = Class.objects.create(name="Grade 2", branch=branch, academic_year=year)
        assignment = ClassStudent.objects.create(student=student, class_obj=class_obj, is_current=False)
        response = self.client.patch(f"/api/students/{student.id}/", {
            "class_students": [{"id": assignment.id, "is_current": True}],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_current)
