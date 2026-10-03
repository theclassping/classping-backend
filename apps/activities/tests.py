from django.test import TestCase
from rest_framework.test import APITestCase

from apps.users.models import User


class ActivityRolePermissionTests(APITestCase):
	def setUp(self):
		self.parent = User.objects.create_user(
			email="activity-parent@example.com",
			password="StrongPassword123!",
			role=User.Role.PARENT,
		)
		self.teacher = User.objects.create_user(
			email="activity-teacher@example.com",
			password="StrongPassword123!",
			role=User.Role.TEACHER,
		)

	def test_parent_can_read_but_cannot_write_activities(self):
		self.client.force_authenticate(user=self.parent)

		self.assertEqual(self.client.get("/api/activities/").status_code, 200)
		self.assertEqual(self.client.get("/api/users/").status_code, 403)
		self.assertEqual(
			self.client.post("/api/activities/", {}, format="json").status_code,
			403,
		)
		self.assertEqual(
			self.client.patch(
				"/api/activities/999999/",
				{},
				format="json",
			).status_code,
			403,
		)
		self.assertEqual(
			self.client.delete("/api/activities/999999/").status_code,
			403,
		)

	def test_teacher_can_read_and_reach_all_write_actions(self):
		self.client.force_authenticate(user=self.teacher)

		self.assertEqual(self.client.get("/api/activities/").status_code, 200)
		self.assertEqual(self.client.get("/api/users/").status_code, 403)
		self.assertEqual(
			self.client.post("/api/activities/", {}, format="json").status_code,
			400,
		)
		self.assertEqual(
			self.client.patch(
				"/api/activities/999999/",
				{},
				format="json",
			).status_code,
			404,
		)
		self.assertEqual(
			self.client.delete("/api/activities/999999/").status_code,
			404,
		)
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.academic_years.models import AcademicYear
from apps.classes.models import Class, ClassTeacher, ClassStudent
from apps.staffs.models import Staff
from apps.students.models import Student
from apps.activities.models import Activity, ActivityImage


class ActivityApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="activity-api@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        location = Location.objects.create(name="Activity Province", code="AP", location_type="PROVINCE")
        school = School.objects.create(name="Activity School", register_number="ACT-001")
        branch = Branch.objects.create(school=school, name="Main", code="MAIN", location=location)
        year = AcademicYear.objects.create(
            branch=branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        teacher_user = User.objects.create_user(
            email="activity-teacher@example.com",
            password="StrongPassword123!",
            role=User.Role.STAFF,
        )
        staff = Staff.objects.create(
            user=teacher_user, branch=branch, first_name="Activity", last_name="Teacher",
            email="activity-teacher@example.com", staff_type=Staff.StaffType.TEACHER,
            hire_date=date(2026, 7, 1), qualification="Education",
        )
        class_obj = Class.objects.create(name="Grade 1", branch=branch, academic_year=year)
        self.class_teacher = ClassTeacher.objects.create(class_obj=class_obj, staff=staff)
        self.student = Student.objects.create(
            first_name="Activity", last_name="Student", date_of_birth=date(2018, 1, 1),
            gender="male", enroll_date=date(2026, 7, 1), status="active",
        )
        ClassStudent.objects.create(
            class_obj=class_obj,
            student=self.student,
            is_current=True,
        )

    def test_create_activity_with_student(self):
        response = self.client.post(
            "/api/activities/",
            {
                "class_teacher_id": self.class_teacher.id,
                "class_id": self.class_teacher.class_obj_id,
                "name": "Science Project",
                "description": "Project work",
                "activity_date": "2026-08-01",
                "student_ids": [self.student.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["activity_students"]), 1)

    def test_activity_students_endpoint_lists_assignment(self):
        activity = self._create_activity()
        response = self.client.get(f"/api/activity-students/?activity_id={activity.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_activity_image_create_and_list(self):
        activity = self._create_activity()
        response = self.client.post(
            "/api/activity-images/",
            {"activity_id": activity.id, "student_id": self.student.id, "caption": "Project photo"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        listing = self.client.get("/api/activity-images/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 1)

    def test_create_activity_with_multiple_nested_images(self):
        response = self.client.post(
            "/api/activities/",
            {
                "class_teacher_id": self.class_teacher.id,
                "class_id": self.class_teacher.class_obj_id,
                "name": "Art Exhibition",
                "activity_date": "2026-08-02",
                "student_ids": [self.student.id],
                "activity_images": [
                    {
                        "image_data": {"object_key": "activities/first.jpg"},
                        "caption": "First image",
                        "position": 1,
                    },
                    {
                        "image_data": {"object_key": "activities/second.jpg"},
                        "caption": "Second image",
                        "position": 2,
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ActivityImage.objects.filter(activity_id=response.data["id"]).count(), 2)
        self.assertEqual(len(response.data["activity_images"]), 2)

    def test_publish_and_unpublish_activity(self):
        activity = self._create_activity()
        response = self.client.patch(
            f"/api/activities/{activity.id}/",
            {"is_publish": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_publish"])
        response = self.client.patch(
            f"/api/activities/{activity.id}/",
            {"is_publish": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_publish"])

    def test_activity_rejects_teacher_from_another_class(self):
        other_class = Class.objects.create(
            name="Grade 2",
            branch=self.class_teacher.class_obj.branch,
            academic_year=self.class_teacher.class_obj.academic_year,
        )
        other_teacher = ClassTeacher.objects.create(
            class_obj=other_class,
            staff=self.class_teacher.staff,
        )
        response = self.client.post(
            "/api/activities/",
            {
                "class_teacher_id": other_teacher.id,
                "class_id": self.class_teacher.class_obj_id,
                "name": "Invalid Activity",
                "activity_date": "2026-08-03",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_activity_student_assignment_is_rejected(self):
        activity = self._create_activity()
        response = self.client.post(
            "/api/activity-students/",
            {"activity_id": activity.id, "student_id": self.student.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_activity_student_update_and_delete(self):
        activity = Activity.objects.create(
            class_teacher=self.class_teacher,
            class_obj=self.class_teacher.class_obj,
            name="Standalone Activity",
            activity_date="2026-08-04",
        )
        create = self.client.post(
            "/api/activity-students/",
            {"activity_id": activity.id, "student_id": self.student.id},
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        assignment_id = create.data["id"]
        detail = self.client.get(f"/api/activity-students/{assignment_id}/")
        self.assertEqual(detail.status_code, 200)
        update = self.client.patch(
            f"/api/activity-students/{assignment_id}/", {}, format="json"
        )
        self.assertEqual(update.status_code, 200)
        delete = self.client.delete(f"/api/activity-students/{assignment_id}/")
        self.assertEqual(delete.status_code, 204)

    def test_activity_image_update_and_delete(self):
        activity = self._create_activity()
        create = self.client.post(
            "/api/activity-images/",
            {"activity_id": activity.id, "image_data": {"object_key": "activity/a.jpg"}},
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        image_id = create.data["id"]
        update = self.client.patch(
            f"/api/activity-images/{image_id}/",
            {"caption": "Updated caption"},
            format="json",
        )
        self.assertEqual(update.status_code, 200)
        delete = self.client.delete(f"/api/activity-images/{image_id}/")
        self.assertEqual(delete.status_code, 204)

    def _create_activity(self):
        response = self.client.post(
            "/api/activities/",
            {
                "class_teacher_id": self.class_teacher.id,
                "class_id": self.class_teacher.class_obj_id,
                "name": "Science Project",
                "activity_date": "2026-08-01",
                "student_ids": [self.student.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return Activity.objects.get(pk=response.data["id"])
