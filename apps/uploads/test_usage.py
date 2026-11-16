"""Branch storage usage: capacity, status, breakdowns, and who may see or change them."""
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.uploads.models import MediaObject
from apps.uploads.test_paths import BranchFixture
from apps.uploads.usage import usage_status
from apps.users.models import RoleModulePermission

Status = MediaObject.Status
GIB = 1024 ** 3


class UsageStatusTests(SimpleTestCase):
    def test_thresholds(self):
        self.assertEqual(usage_status(79, 100), "ok")
        self.assertEqual(usage_status(80, 100), "warning")
        self.assertEqual(usage_status(100, 100), "warning")
        self.assertEqual(usage_status(101, 100), "over")
        self.assertEqual(usage_status(0, 0), "ok")
        self.assertEqual(usage_status(1, 0), "over")


@override_settings(DEFAULT_BRANCH_STORAGE_BYTES=1000)
class StorageUsageApiTests(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.media("a1", self.branch_a, 300, "activities", self.class_a)
        self.media("a2", self.branch_a, 200, "payments", self.class_a, status=Status.PENDING)
        self.media("a3", self.branch_a, 100, "students")
        self.media("gone", self.branch_a, 5000, "activities", self.class_a, status=Status.DELETED)
        self.media("b1", self.branch_b, 900, "activities", self.class_b)
        self.branch_other.storage_capacity_bytes = 100_000
        self.branch_other.save()

    def media(self, key, branch, size, category, class_obj=None, status=Status.ATTACHED):
        MediaObject.objects.create(
            file_key=key, branch=branch, class_obj=class_obj, category=category, size_bytes=size, status=status,
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_branch_report_breaks_down_by_category_and_class(self):
        response = self.client_for(self.admin).get(f"/api/branches/{self.branch_a.pk}/storage-usage/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        # Deleted files no longer count; pending ones do.
        self.assertEqual(
            (data["used_bytes"], data["pending_bytes"], data["files"], data["capacity_bytes"], data["capacity_is_default"]),
            (600, 200, 3, 1000, True),
        )
        self.assertEqual((data["percent"], data["status"]), (60.0, "ok"))
        self.assertEqual(
            [(row["category"], row["used_bytes"]) for row in data["by_category"]],
            [("activities", 300), ("payments", 200), ("students", 100)],
        )
        [class_row] = data["by_class"]
        self.assertEqual((class_row["class_id"], class_row["used_bytes"], class_row["files"]), (self.class_a.pk, 500, 2))

    def test_custom_capacity_overrides_default(self):
        self.branch_a.storage_capacity_bytes = 500
        self.branch_a.save()
        data = self.client_for(self.admin).get(f"/api/branches/{self.branch_a.pk}/storage-usage/").data
        self.assertEqual((data["capacity_bytes"], data["capacity_is_default"], data["status"]), (500, False, "over"))

    def test_list_puts_fullest_branch_first(self):
        response = self.client_for(self.admin).get("/api/branches/storage-usage/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [(row["branch_id"], row["used_bytes"], row["status"]) for row in response.data],
            [(self.branch_b.pk, 900, "warning"), (self.branch_a.pk, 600, "ok"), (self.branch_other.pk, 0, "ok")],
        )

    def test_branch_staff_see_only_their_branch(self):
        client = self.client_for(self.officer_user)
        self.assertEqual([row["branch_id"] for row in client.get("/api/branches/storage-usage/").data], [self.branch_a.pk])
        self.assertEqual(client.get(f"/api/branches/{self.branch_a.pk}/storage-usage/").status_code, 200)
        self.assertEqual(client.get(f"/api/branches/{self.branch_b.pk}/storage-usage/").status_code, 404)

    def test_teachers_and_parents_cannot_see_usage(self):
        for user in (self.teacher_user, self.parent_user):
            client = self.client_for(user)
            self.assertEqual(client.get("/api/branches/storage-usage/").status_code, 403)
            self.assertEqual(client.get(f"/api/branches/{self.branch_a.pk}/storage-usage/").status_code, 403)

    def test_only_admins_change_capacity(self):
        RoleModulePermission.objects.update_or_create(
            role="STAFF", module="schools", defaults={"can_read": True, "can_edit": True},
        )
        url = f"/api/branches/{self.branch_a.pk}/"
        response = self.client_for(self.officer_user).patch(url, {"storage_capacity_bytes": 10 * GIB}, format="json")
        self.assertEqual(response.status_code, 403, response.data)
        # Other fields stay editable for staff.
        response = self.client_for(self.officer_user).patch(url, {"phone": "123"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        response = self.client_for(self.admin).patch(url, {"storage_capacity_bytes": 10 * GIB}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["storage_capacity_bytes"], 10 * GIB)
        response = self.client_for(self.admin).patch(url, {"storage_capacity_bytes": None}, format="json")
        self.branch_a.refresh_from_db()
        self.assertIsNone(self.branch_a.storage_capacity_bytes)


@override_settings(DEFAULT_BRANCH_STORAGE_BYTES=5 * GIB)
class AdminWebStorageTests(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.client.force_login(self.admin)
        MediaObject.objects.create(
            file_key="k", branch=self.branch_b, class_obj=self.class_b, category="activities", size_bytes=2048,
        )

    def edit(self, capacity):
        branch = self.branch_a
        return self.client.post(reverse("admin_web:branch_edit", args=[self.school.pk, branch.pk]), {
            "name": branch.name, "code": branch.code, "location_id": branch.location_id,
            "is_active": "on", "storage_capacity_gb": capacity,
        })

    def test_capacity_is_set_in_gb_and_cleared_to_default(self):
        self.assertEqual(self.edit("2.5").status_code, 302)
        self.branch_a.refresh_from_db()
        self.assertEqual(self.branch_a.storage_capacity_bytes, int(2.5 * GIB))
        form = self.client.get(reverse("admin_web:branch_edit", args=[self.school.pk, self.branch_a.pk]))
        self.assertContains(form, 'value="2.5"')

        self.assertEqual(self.edit("").status_code, 302)
        self.branch_a.refresh_from_db()
        self.assertIsNone(self.branch_a.storage_capacity_bytes)

    def test_unchanged_form_keeps_exact_capacity(self):
        self.branch_a.storage_capacity_bytes = GIB + 1  # e.g. set through the API
        self.branch_a.save()
        self.assertEqual(self.edit("1").status_code, 302)
        self.branch_a.refresh_from_db()
        self.assertEqual(self.branch_a.storage_capacity_bytes, GIB + 1)

    def test_invalid_capacity_is_rejected(self):
        for value in ("-1", "0", "abc", "nan", "1e20"):
            response = self.edit(value)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Storage capacity must")
        self.branch_a.refresh_from_db()
        self.assertIsNone(self.branch_a.storage_capacity_bytes)

    def test_overview_and_detail_show_usage(self):
        overview = self.client.get(reverse("admin_web:storage_overview"))
        self.assertContains(overview, "2.0\xa0KB")
        rows = overview.context["rows"]
        self.assertEqual(rows[0]["branch_id"], self.branch_b.pk)
        detail = self.client.get(reverse("admin_web:branch_detail", args=[self.school.pk, self.branch_b.pk]))
        self.assertContains(detail, self.class_b.name)
        self.assertContains(detail, "Activities")


@override_settings(STORAGE_TYPE="local", DEFAULT_BRANCH_STORAGE_BYTES=1000, ENFORCE_BRANCH_STORAGE_CAPACITY=True)
class StorageCapacityEnforcementTests(BranchFixture, TestCase):
    """A full branch gets no new uploads; deleted files free their space."""

    def setUp(self):
        from unittest.mock import patch
        from apps.uploads.services.media import MediaService
        from apps.uploads.storage import StorageFactory

        self.make_fixture()
        StorageFactory.reset()
        self.addCleanup(StorageFactory.reset)
        patch.object(MediaService, "_redis", return_value=None).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(MediaService._pending_uploads.clear)
        MediaObject.objects.create(file_key="used", branch=self.branch_a, category="students", size_bytes=700)

    def presign(self, size, branch=None):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client.post("/api/media/presign/", {
            "filename": "photo.jpg", "content_type": "image/jpeg", "size": size,
            "purpose": "student", "branch_id": (branch or self.branch_a).pk,
        }, format="json")

    def test_upload_that_fits_exactly_is_allowed_and_counted(self):
        self.assertEqual(self.presign(300).status_code, 200)
        # The pending upload now fills the branch, so the next byte is refused.
        response = self.presign(1)
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            (response.data["code"], response.data["used_bytes"], response.data["capacity_bytes"]),
            ("storage_full", 1000, 1000),
        )

    def test_upload_over_capacity_is_refused_without_a_pending_row(self):
        response = self.presign(301)
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["requested_bytes"], 301)
        self.assertEqual(MediaObject.objects.filter(branch=self.branch_a).count(), 1)

    def test_other_branches_and_deleted_files_do_not_count(self):
        self.assertEqual(self.presign(1000, branch=self.branch_b).status_code, 200)
        MediaObject.objects.filter(file_key="used").update(status=Status.DELETED)
        self.assertEqual(self.presign(1000).status_code, 200)

    def test_custom_capacity_raises_the_limit(self):
        self.branch_a.storage_capacity_bytes = 2000
        self.branch_a.save()
        self.assertEqual(self.presign(1300).status_code, 200)

    def test_enforcement_can_be_switched_off(self):
        with override_settings(ENFORCE_BRANCH_STORAGE_CAPACITY=False):
            self.assertEqual(self.presign(5000).status_code, 200)


class LocalDiskFullTests(SimpleTestCase):
    def test_disk_full_returns_507_and_removes_partial_file(self):
        import errno
        import os
        import tempfile
        from unittest.mock import mock_open, patch
        from apps.uploads.storage import make_upload_token

        key = "branch_1/general/full.jpg"
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            target = os.path.join(media_root, key)
            os.makedirs(os.path.dirname(target))
            open(target, "wb").close()  # what a failed write leaves behind
            token = make_upload_token(key, 600, content_type="image/jpeg", content_length=3)
            failing = mock_open()
            failing.return_value.write.side_effect = OSError(errno.ENOSPC, "No space left on device")
            with patch("apps.uploads.views.open", failing, create=True):
                response = APIClient().put(
                    f"/api/media/upload/{key}?token={token}", data=b"abc", content_type="image/jpeg",
                )
            self.assertEqual(response.status_code, 507)
            self.assertEqual(response.data["code"], "server_storage_full")
            self.assertFalse(os.path.exists(target))


@override_settings(DEFAULT_BRANCH_STORAGE_BYTES=1000, ENFORCE_BRANCH_STORAGE_CAPACITY=True)
class AdminWebUploadCapacityTests(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        MediaObject.objects.create(file_key="used", branch=self.branch_a, category="students", size_bytes=700)

    def form_errors(self, size):
        from unittest.mock import patch
        from django import forms
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.admin_web.forms import SearchableImageUploadMixin
        from apps.uploads.paths import MediaLocation

        class UploadForm(SearchableImageUploadMixin, forms.Form):
            image_file = forms.FileField(required=False)

        form = UploadForm(data={}, files={"image_file": SimpleUploadedFile("a.jpg", b"x" * size, "image/jpeg")})
        form.instance = object()
        location = MediaLocation(self.branch_a.pk, None, "students")
        with patch("apps.admin_web.forms.instance_media_location", return_value=location):
            form.is_valid()
        return form.errors.get("image_file", [])

    def test_upload_into_a_full_branch_is_a_form_error(self):
        self.assertEqual(self.form_errors(300), [])
        [message] = self.form_errors(301)
        self.assertIn("storage is full", message)
