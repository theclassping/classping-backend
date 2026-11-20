"""When a branch is full: reset images by category/class, or request an add-on a superadmin approves."""
from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.activities.models import Activity, ActivityImage
from apps.uploads.models import MediaObject
from apps.uploads.paths import build_media_key
from apps.uploads.services.media import MediaService
from apps.uploads.storage import StorageFactory
from apps.uploads.test_paths import BranchFixture
from apps.users.models import User

Status = MediaObject.Status
GIB = 1024 ** 3


class QuotaTestCase(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        patch.object(MediaService, "_redis", return_value=None).start()
        self.delete_object = patch.object(MediaService, "delete_object").start()
        self.addCleanup(patch.stopall)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def used(self, branch):
        return sum(MediaObject.objects.filter(branch=branch, status__in=(Status.PENDING, Status.ATTACHED))
                   .values_list("size_bytes", flat=True))


class StorageResetTests(QuotaTestCase):
    def setUp(self):
        super().setUp()
        activity = Activity.objects.create(
            class_teacher=self.class_teacher, class_obj=self.class_a, name="Trip", activity_date=date(2026, 8, 1),
        )
        self.images = []
        for size in (100, 200):
            key = build_media_key("activity", self.branch_a.pk, self.class_a.pk, ".jpg")
            self.images.append(ActivityImage.objects.create(activity=activity, image_data={"id": key, "size": size}))
        self.student_key = build_media_key("student", self.branch_a.pk, extension=".jpg")
        self.student_a.image_data = {"id": self.student_key, "size": 50}
        self.student_a.save()
        self.url = f"/api/branches/{self.branch_a.pk}/storage-reset/"

    def reset(self, user=None, **body):
        return self.client_for(user or self.officer_user).post(self.url, body, format="json")

    def test_dry_run_reports_without_changing_anything(self):
        response = self.reset(category="activities", class_id=self.class_a.pk, dry_run=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["files"], response.data["bytes"]), (2, 300))
        self.images[0].refresh_from_db()
        self.assertIsNotNone(self.images[0].image_data)
        self.delete_object.assert_not_called()

    def test_reset_clears_images_keeps_records_and_frees_space(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.reset(category="activities", class_id=self.class_a.pk)
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual((response.data["files"], response.data["bytes"]), (2, 300))
        for image in self.images:
            image.refresh_from_db()
            self.assertIsNone(image.image_data)
        self.assertEqual(self.delete_object.call_count, 2)
        # Only the student photo is left.
        self.assertEqual(self.used(self.branch_a), 50)
        self.student_a.refresh_from_db()
        self.assertIsNotNone(self.student_a.image_data)

    def test_failed_delete_stays_counted_and_a_rerun_retries_it(self):
        self.delete_object.side_effect = [RuntimeError("storage down"), None]
        with self.captureOnCommitCallbacks(execute=True):
            self.reset(category="activities")
        self.assertEqual(self.used(self.branch_a), 50 + 100)
        self.delete_object.side_effect = None
        with self.captureOnCommitCallbacks(execute=True):
            response = self.reset(category="activities")
        self.assertEqual(response.data["files"], 1)
        self.assertEqual(self.used(self.branch_a), 50)

    def test_category_without_class_covers_the_whole_branch(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.reset(category="students")
        self.assertEqual((response.data["files"], response.data["bytes"]), (1, 50))
        self.student_a.refresh_from_db()
        self.assertIsNone(self.student_a.image_data)

    def test_payment_proofs_and_unknown_categories_are_refused(self):
        for category in ("payments", "nope", None):
            response = self.reset(category=category)
            self.assertEqual(response.status_code, 400, category)

    def test_class_of_another_branch_is_refused(self):
        self.assertEqual(self.reset(category="activities", class_id=self.class_b.pk).status_code, 400)

    def test_only_branch_staff_and_admins(self):
        self.assertEqual(self.reset(user=self.teacher_user, category="students", dry_run=True).status_code, 403)
        self.assertEqual(self.reset(user=self.parent_user, category="students", dry_run=True).status_code, 403)
        other = self.client_for(self.officer_user).post(
            f"/api/branches/{self.branch_b.pk}/storage-reset/", {"category": "students"}, format="json",
        )
        self.assertEqual(other.status_code, 404)
        self.assertEqual(self.reset(user=self.admin, category="students", dry_run=True).status_code, 200)
