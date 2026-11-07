"""Branch-rooted upload keys: building, presign context, and attach checks."""
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.academic_years.models import AcademicYear
from apps.activities.models import Activity, ActivityImage
from apps.assessments.models import AssessmentImage
from apps.classes.models import Class, ClassStudent, ClassTeacher
from apps.guardians.models import Guardian
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.staffs.models import Staff
from apps.students.models import Student, StudentGuardian
from apps.uploads.paths import (
    MediaLocation,
    MediaLocationMismatch,
    build_media_key,
    check_media_location,
    media_key_for_instance,
    parse_media_key,
)
from apps.uploads.services.media import MediaService
from apps.uploads.storage import StorageFactory
from apps.users.models import User


class MediaKeyFormatTests(SimpleTestCase):
    def test_class_purpose_key(self):
        key = build_media_key("activity", 3, 12, ".jpg")
        self.assertRegex(key, r"^branch_3/class_12/activities/[0-9a-f]{32}\.jpg$")
        self.assertEqual(parse_media_key(key), MediaLocation(3, 12, "activities"))

    def test_branch_purpose_key(self):
        for purpose, category in (("student", "students"), ("guardian", "guardians"), ("general", "general")):
            key = build_media_key(purpose, 3, extension=".png")
            self.assertRegex(key, rf"^branch_3/{category}/[0-9a-f]{{32}}\.png$")
            self.assertEqual(parse_media_key(key), MediaLocation(3, None, category))

    def test_branch_purpose_ignores_class_id(self):
        self.assertTrue(build_media_key("student", 3, 12).startswith("branch_3/students/"))

    def test_class_purpose_requires_class(self):
        with self.assertRaises(ValueError):
            build_media_key("payment", 3)

    def test_unknown_purpose_rejected(self):
        with self.assertRaises(ValueError):
            build_media_key("documents", 3)

    def test_legacy_and_malformed_keys_do_not_parse(self):
        for key in (
            "2026/11/08/abc.jpg",
            "branch_3/class_12/students/abc.jpg",   # branch category inside a class folder
            "branch_3/activities/abc.jpg",          # class category without a class
            "branch_3/class_12/other/abc.jpg",
            "branch_x/students/abc.jpg",
            "branch_3/students/sub/abc.jpg",
        ):
            self.assertIsNone(parse_media_key(key), key)


class BranchFixture:
    """Two branches of one school, a class in each, and a third unrelated branch."""

    def make_fixture(self):
        location = Location.objects.create(name="Path Province", code="PTH", location_type="PROVINCE")
        self.school = School.objects.create(name="Path School", register_number="PTH-001")
        self.branch_a = Branch.objects.create(school=self.school, name="A", code="A", location=location)
        self.branch_b = Branch.objects.create(school=self.school, name="B", code="B", location=location)
        other_school = School.objects.create(name="Other School", register_number="PTH-002")
        self.branch_other = Branch.objects.create(school=other_school, name="O", code="O", location=location)

        def make_class(branch):
            year = AcademicYear.objects.create(
                branch=branch, name="2026/2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30),
            )
            return Class.objects.create(name=f"Grade 1 {branch.code}", branch=branch, academic_year=year)

        self.class_a = make_class(self.branch_a)
        self.class_b = make_class(self.branch_b)

        self.admin = User.objects.create_user(
            email="path-admin@example.com", password="StrongPassword123!", role=User.Role.ADMIN,
        )
        self.teacher_user = User.objects.create_user(
            email="path-teacher@example.com", password="StrongPassword123!", role=User.Role.TEACHER,
        )
        self.teacher = Staff.objects.create(
            user=self.teacher_user, branch=self.branch_a, first_name="Path", last_name="Teacher",
            email="path-teacher@example.com", staff_type=Staff.StaffType.TEACHER,
            hire_date=date(2026, 7, 1), qualification="Education",
        )
        self.class_teacher = ClassTeacher.objects.create(class_obj=self.class_a, staff=self.teacher)
        self.officer_user = User.objects.create_user(
            email="path-officer@example.com", password="StrongPassword123!", role=User.Role.STAFF,
        )
        Staff.objects.create(
            user=self.officer_user, branch=self.branch_a, first_name="Path", last_name="Officer",
            email="path-officer@example.com", staff_type=Staff.StaffType.OFFICER,
            hire_date=date(2026, 7, 1), qualification="Admin",
        )

        # A parent with one child in each branch.
        self.parent_user = User.objects.create_user(
            email="path-parent@example.com", password="StrongPassword123!", role=User.Role.PARENT,
        )
        self.guardian = Guardian.objects.create(user=self.parent_user, name="Path Parent")
        self.student_a = self._student("Alpha", self.branch_a, self.class_a)
        self.student_b = self._student("Beta", self.branch_b, self.class_b)

    def _student(self, name, branch, class_obj):
        student = Student.objects.create(
            first_name=name, last_name="Child", date_of_birth=date(2018, 1, 1),
            gender="other", enroll_date=date(2026, 7, 1), status="active", branch=branch,
        )
        ClassStudent.objects.create(class_obj=class_obj, student=student, is_current=True)
        StudentGuardian.objects.create(
            student=student, guardian=self.guardian, relationship="mother", is_primary=True,
        )
        return student


@override_settings(STORAGE_TYPE="local")
class PresignLocationTests(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        StorageFactory.reset()
        self.addCleanup(StorageFactory.reset)
        patch.object(MediaService, "_redis", return_value=None).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(MediaService._pending_uploads.clear)

    def presign(self, user, **context):
        client = APIClient()
        client.force_authenticate(user=user)
        body = {"filename": "photo.jpg", "content_type": "image/jpeg", "size": 1000, **context}
        return client.post("/api/media/presign/", body, format="json")

    def test_class_upload_goes_under_its_branch_and_class(self):
        response = self.presign(self.admin, purpose="activity", class_id=self.class_b.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            response.data["file_key"].startswith(f"branch_{self.branch_b.pk}/class_{self.class_b.pk}/activities/")
        )
        pending = MediaService._pending_uploads[response.data["file_key"]]
        self.assertEqual(pending["branch_id"], self.branch_b.pk)
        self.assertEqual(pending["class_id"], self.class_b.pk)

    def test_teacher_cannot_presign_for_a_class_they_do_not_teach(self):
        self.assertEqual(self.presign(self.teacher_user, purpose="assessment", class_id=self.class_a.pk).status_code, 200)
        self.assertEqual(self.presign(self.teacher_user, purpose="assessment", class_id=self.class_b.pk).status_code, 404)

    def test_class_purpose_requires_class_id(self):
        self.assertEqual(self.presign(self.admin, purpose="payment").status_code, 400)

    def test_staff_branch_used_when_branch_not_sent(self):
        response = self.presign(self.officer_user, purpose="student")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["file_key"].startswith(f"branch_{self.branch_a.pk}/students/"))

    def test_staff_cannot_upload_into_another_branch(self):
        self.assertEqual(self.presign(self.officer_user, purpose="student", branch_id=self.branch_b.pk).status_code, 404)

    def test_admin_with_many_branches_must_name_one(self):
        self.assertEqual(self.presign(self.admin, purpose="general").status_code, 400)
        response = self.presign(self.admin, purpose="general", branch_id=self.branch_b.pk)
        self.assertTrue(response.data["file_key"].startswith(f"branch_{self.branch_b.pk}/general/"))

    def test_parent_with_children_in_two_branches_must_name_one_of_them(self):
        self.assertEqual(self.presign(self.parent_user, purpose="guardian").status_code, 400)
        response = self.presign(self.parent_user, purpose="guardian", branch_id=self.branch_b.pk)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["file_key"].startswith(f"branch_{self.branch_b.pk}/guardians/"))
        self.assertEqual(
            self.presign(self.parent_user, purpose="guardian", branch_id=self.branch_other.pk).status_code, 404,
        )

    def test_parent_with_one_branch_needs_no_branch_id(self):
        self.student_b.student_guardians.all().delete()
        response = self.presign(self.parent_user, purpose="guardian")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["file_key"].startswith(f"branch_{self.branch_a.pk}/guardians/"))

    def test_without_purpose_the_legacy_key_is_used(self):
        response = self.presign(self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.data["file_key"], r"^\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.jpg$")

    def test_unknown_purpose_rejected(self):
        self.assertEqual(self.presign(self.admin, purpose="documents").status_code, 400)


class AttachLocationTests(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.activity = Activity.objects.create(
            class_teacher=self.class_teacher, class_obj=self.class_a, name="Trip", activity_date=date(2026, 8, 1),
        )

    def key(self, purpose, branch, class_obj=None):
        return build_media_key(purpose, branch.pk, class_obj.pk if class_obj else None, ".jpg")

    def test_activity_image_must_use_its_class_folder(self):
        ActivityImage.objects.create(activity=self.activity, image_data={"id": self.key("activity", self.branch_a, self.class_a)})
        with self.assertRaises(MediaLocationMismatch):
            ActivityImage.objects.create(activity=self.activity, image_data={"id": self.key("activity", self.branch_b, self.class_b)})

    def test_wrong_category_rejected(self):
        with self.assertRaises(MediaLocationMismatch):
            ActivityImage.objects.create(
                activity=self.activity, image_data={"id": self.key("assessment", self.branch_a, self.class_a)},
            )

    def test_class_from_another_branch_with_matching_id_shape_rejected(self):
        forged = f"branch_{self.branch_b.pk}/class_{self.class_a.pk}/activities/abc.jpg"
        with self.assertRaises(MediaLocationMismatch):
            ActivityImage.objects.create(activity=self.activity, image_data={"id": forged})

    def test_legacy_key_still_attaches(self):
        ActivityImage.objects.create(activity=self.activity, image_data={"id": "2026/11/08/legacy.jpg"})

    def test_unchanged_key_is_not_rechecked(self):
        image = ActivityImage.objects.create(
            activity=self.activity, image_data={"id": self.key("activity", self.branch_a, self.class_a)},
        )
        # Moving the activity to another class later must not block edits.
        Activity.objects.filter(pk=self.activity.pk).update(class_obj=self.class_b)
        image.refresh_from_db()
        image.caption = "edited"
        image.save()

    def test_student_photo_must_be_in_students_branch(self):
        self.student_a.image_data = {"id": self.key("student", self.branch_a)}
        self.student_a.save()
        self.student_b.image_data = {"id": self.key("student", self.branch_a)}
        with self.assertRaises(MediaLocationMismatch):
            self.student_b.save()

    def test_guardian_photo_must_be_in_a_childs_branch(self):
        for branch in (self.branch_a, self.branch_b):
            self.guardian.image_data = {"id": self.key("guardian", branch)}
            self.guardian.save()
        self.guardian.image_data = {"id": self.key("guardian", self.branch_other)}
        with self.assertRaises(MediaLocationMismatch):
            self.guardian.save()

    def test_new_guardian_without_children_accepts_any_guardian_folder(self):
        user = User.objects.create_user(email="path-new@example.com", password="StrongPassword123!", role=User.Role.PARENT)
        Guardian.objects.create(user=user, name="New", image_data={"id": self.key("guardian", self.branch_other)})
        with self.assertRaises(MediaLocationMismatch):
            Guardian.objects.create(
                user=User.objects.create_user(
                    email="path-new2@example.com", password="StrongPassword123!", role=User.Role.PARENT,
                ),
                name="New 2",
                image_data={"id": self.key("student", self.branch_a)},
            )

    def test_school_logo_must_be_in_one_of_its_branches(self):
        self.school.image_data = {"id": self.key("general", self.branch_b)}
        self.school.save()
        self.school.image_data = {"id": self.key("general", self.branch_other)}
        with self.assertRaises(MediaLocationMismatch):
            self.school.save()

    def test_api_returns_400_for_mismatched_key(self):
        from apps.activities.tests import accept_image_data_as_sent
        accept_image_data_as_sent(self)
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.post(
            "/api/activity-images/",
            {"activity_id": self.activity.pk, "image_data": self.key("activity", self.branch_b, self.class_b)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("image_data", response.data)
        self.assertFalse(ActivityImage.objects.exists())

    def test_admin_web_key_follows_the_record(self):
        image = ActivityImage(activity=self.activity)
        self.assertTrue(
            media_key_for_instance(image, ".jpg").startswith(f"branch_{self.branch_a.pk}/class_{self.class_a.pk}/activities/")
        )
        self.assertTrue(media_key_for_instance(self.student_b, ".jpg").startswith(f"branch_{self.branch_b.pk}/students/"))
        # A guardian with no children yet has no branch: caller falls back to a legacy key.
        self.assertIsNone(media_key_for_instance(Guardian(name="Nobody"), ".jpg"))
        # An image whose activity isn't linked yet also falls back.
        self.assertIsNone(media_key_for_instance(AssessmentImage(), ".jpg"))
        # The generated key passes the attach check.
        check_media_location(image, media_key_for_instance(image, ".jpg"))
