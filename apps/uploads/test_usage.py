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
