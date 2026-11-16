"""When a branch is full: reset images by category/class, or request an add-on a superadmin approves."""
from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.activities.models import Activity, ActivityImage
from apps.uploads.models import MediaObject, StorageAddOn
from apps.uploads.paths import build_media_key
from apps.uploads.services.media import MediaService
from apps.uploads.storage import StorageFactory
from apps.uploads.test_paths import BranchFixture
from apps.uploads.usage import capacity_of
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


@override_settings(STORAGE_TYPE="local", DEFAULT_BRANCH_STORAGE_BYTES=GIB, ENFORCE_BRANCH_STORAGE_CAPACITY=True)
class StorageAddOnTests(QuotaTestCase):
    def setUp(self):
        super().setUp()
        StorageFactory.reset()
        self.addCleanup(StorageFactory.reset)
        self.addCleanup(MediaService._pending_uploads.clear)
        MediaObject.objects.create(file_key="full", branch=self.branch_a, category="students", size_bytes=GIB)
        self.url = f"/api/branches/{self.branch_a.pk}/storage-addons/"
        self.superadmin = User.objects.create_superuser(email="root@example.com", password="StrongPassword123!")

    def request_addon(self, size_gb=2, user=None):
        return self.client_for(user or self.officer_user).post(self.url, {"size_gb": size_gb, "note": "Paid"}, format="json")

    def presign(self):
        return self.client_for(self.officer_user).post("/api/media/presign/", {
            "filename": "a.jpg", "content_type": "image/jpeg", "size": 1000, "purpose": "student",
        }, format="json")

    def review(self, addon, decision, user=None):
        self.client.force_login(user or self.superadmin)
        return self.client.post(
            reverse("admin_web:storage_addon_review", args=[self.school.pk, self.branch_a.pk, addon.pk]),
            {"decision": decision, "review_note": "TRX-1"},
        )

    def test_request_is_pending_until_approved_then_capacity_grows(self):
        response = self.request_addon()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["status"], response.data["size_bytes"]), ("pending", 2 * GIB))
        self.assertEqual(self.presign().status_code, 403)

        addon = StorageAddOn.objects.get()
        self.assertEqual(self.review(addon, "approve").status_code, 302)
        addon.refresh_from_db()
        self.assertEqual((addon.status, addon.reviewed_by, addon.review_note), ("approved", self.superadmin, "TRX-1"))
        self.assertEqual(capacity_of(self.branch_a), 3 * GIB)
        self.assertEqual(self.presign().status_code, 200)

        report = self.client_for(self.officer_user).get(f"/api/branches/{self.branch_a.pk}/storage-usage/").data
        self.assertEqual((report["base_capacity_bytes"], report["addon_bytes"]), (GIB, 2 * GIB))
        listed = self.client_for(self.admin).get("/api/branches/storage-usage/").data
        self.assertEqual(next(r for r in listed if r["branch_id"] == self.branch_a.pk)["capacity_bytes"], 3 * GIB)

    def test_rejected_and_cancelled_add_no_capacity(self):
        self.request_addon()
        self.review(StorageAddOn.objects.get(), "reject")
        self.request_addon()
        pending = StorageAddOn.objects.get(status="pending")
        response = self.client_for(self.officer_user).post(f"{self.url}{pending.pk}/cancel/")
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(capacity_of(self.branch_a), GIB)
        self.assertEqual(len(self.client_for(self.officer_user).get(self.url).data), 2)

    def test_one_pending_request_at_a_time_and_size_is_validated(self):
        for bad in (0, -1, 1001, "2", 1.5, None):
            self.assertEqual(self.request_addon(size_gb=bad).status_code, 400, bad)
        self.assertEqual(self.request_addon().status_code, 201)
        self.assertEqual(self.request_addon().status_code, 400)

    def test_only_superadmin_approves_and_only_once(self):
        self.request_addon()
        addon = StorageAddOn.objects.get()
        self.assertEqual(self.review(addon, "approve", user=self.admin).status_code, 403)
        self.review(addon, "approve")
        self.review(addon, "reject")
        addon.refresh_from_db()
        self.assertEqual(addon.status, "approved")

    def test_teachers_cannot_request(self):
        self.assertEqual(self.request_addon(user=self.teacher_user).status_code, 403)

    def test_pending_requests_are_listed_for_superadmin(self):
        self.request_addon()
        self.client.force_login(self.superadmin)
        response = self.client.get(reverse("admin_web:storage_overview"))
        self.assertEqual(len(response.context["pending_addons"]), 1)
