from django.test import TestCase

# Create your tests here.
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.academic_years.models import AcademicYear
from apps.staffs.models import Staff
from apps.students.models import Student
from apps.classes.models import ClassTeacher, ClassStudent


class ClassRelationshipApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="class-api@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        location = Location.objects.create(name="Class Province", code="CP", location_type="PROVINCE")
        school = School.objects.create(name="Class School", register_number="CLASS-001")
        branch = Branch.objects.create(school=school, name="Main", code="MAIN", location=location)
        academic_year = AcademicYear.objects.create(
            branch=branch,
            name="2026/2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        staff_user = User.objects.create_user(
            email="teacher-api@example.com",
            password="StrongPassword123!",
            role=User.Role.STAFF,
        )
        self.staff = Staff.objects.create(
            user=staff_user,
            branch=branch,
            first_name="Class",
            last_name="Teacher",
            email="teacher-api@example.com",
            staff_type=Staff.StaffType.TEACHER,
            hire_date=date(2026, 7, 1),
            qualification="Education",
        )
        self.student = Student.objects.create(
            first_name="Class",
            last_name="Student",
            date_of_birth=date(2018, 1, 1),
            gender="male",
            enroll_date=date(2026, 7, 1),
            status="active",
        )
        self.class_obj = self._create_class(branch.id, academic_year.id)

    def _create_class(self, branch_id, academic_year_id):
        response = self.client.post(
            "/api/classes/",
            {"name": "Grade 1", "branch": branch_id, "academic_year": academic_year_id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        from apps.classes.models import Class
        return Class.objects.get(pk=response.data["id"])

    def test_assign_teacher_and_list_class_teachers(self):
        response = self.client.post(
            "/api/class-teachers/",
            {"class_id": self.class_obj.id, "staff_id": self.staff.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        listing = self.client.get(f"/api/classes/{self.class_obj.id}/teachers/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 1)

    def test_class_teacher_index_filters_by_class_id(self):
        self.client.post(
            "/api/class-teachers/",
            {"class_id": self.class_obj.id, "staff_id": self.staff.id},
            format="json",
        )
        response = self.client.get(f"/api/class-teachers/?class_id={self.class_obj.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["class_id"], self.class_obj.id)

    def test_assign_student_and_list_class_students(self):
        response = self.client.post(
            "/api/class-students/",
            {"class_id": self.class_obj.id, "student_id": self.student.id, "is_current": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        listing = self.client.get(f"/api/classes/{self.class_obj.id}/students/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 1)

    def test_class_full_update_and_delete(self):
        detail = self.client.get(f"/api/classes/{self.class_obj.id}/")
        self.assertEqual(detail.status_code, 200)
        update = self.client.put(f"/api/classes/{self.class_obj.id}/", {
            "name": "Grade 1 Updated", "branch": self.class_obj.branch_id,
            "academic_year": self.class_obj.academic_year_id,
        }, format="json")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data["name"], "Grade 1 Updated")
        delete = self.client.delete(f"/api/classes/{self.class_obj.id}/")
        self.assertEqual(delete.status_code, 204)

    def test_duplicate_class_and_invalid_references_fail(self):
        duplicate = self.client.post("/api/classes/", {
            "name": "Grade 1", "branch": self.class_obj.branch_id,
            "academic_year": self.class_obj.academic_year_id,
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)
        invalid_class = self.client.post("/api/classes/", {
            "name": "Invalid", "branch": 999999, "academic_year": 999999,
        }, format="json")
        self.assertEqual(invalid_class.status_code, 400)
        invalid_teacher = self.client.post("/api/class-teachers/", {
            "class_id": 999999, "staff_id": self.staff.id,
        }, format="json")
        self.assertEqual(invalid_teacher.status_code, 400)
        invalid_student = self.client.post("/api/class-students/", {
            "class_id": self.class_obj.id, "student_id": 999999,
        }, format="json")
        self.assertEqual(invalid_student.status_code, 400)
