"""MediaObject keeps one row per stored file, counted against its branch."""
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import transaction
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.activities.models import Activity, ActivityImage
from apps.uploads.models import MediaObject
from apps.uploads.paths import MediaLocation, build_media_key
from apps.uploads.services.media import MediaService
from apps.uploads.storage import StorageFactory
from apps.uploads.test_paths import BranchFixture

Status = MediaObject.Status


class TrackingTestCase(BranchFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.activity = Activity.objects.create(
            class_teacher=self.class_teacher, class_obj=self.class_a, name="Trip", activity_date=date(2026, 8, 1),
        )
        patch.object(MediaService, "_redis", return_value=None).start()
        self.delete_object = patch("apps.uploads.signals.MediaService.delete_object").start()
        self.addCleanup(patch.stopall)
        self.addCleanup(MediaService._pending_uploads.clear)

    def class_key(self, class_obj=None):
        class_obj = class_obj or self.class_a
        return build_media_key("activity", class_obj.branch_id, class_obj.pk, ".jpg")

    def row(self, key):
        return MediaObject.objects.get(file_key=key)

    def usage(self, branch):
        return MediaObject.objects.filter(
            branch=branch, status__in=[Status.PENDING, Status.ATTACHED],
        ).aggregate(total=Sum("size_bytes"))["total"] or 0


@override_settings(STORAGE_TYPE="local")
class LifecycleTests(TrackingTestCase):
    def test_presign_records_pending_with_signed_size(self):
        StorageFactory.reset()
        self.addCleanup(StorageFactory.reset)
        location = MediaLocation(self.branch_a.pk, self.class_a.pk, "activities")
        result = MediaService.generate_presign_url(
            "a.jpg", "image/jpeg", size=5000, user_id=self.admin.pk, location=location,
        )
        row = self.row(result["file_key"])
        self.assertEqual(
            (row.status, row.branch_id, row.class_obj_id, row.category, row.size_bytes, row.created_by_id),
            (Status.PENDING, self.branch_a.pk, self.class_a.pk, "activities", 5000, self.admin.pk),
        )
        self.assertEqual(self.usage(self.branch_a), 5000)

    def test_attach_marks_attached_with_stored_size(self):
        key = self.class_key()
        MediaObject.objects.create(file_key=key, branch=self.branch_a, size_bytes=5000)
        ActivityImage.objects.create(
            activity=self.activity, image_data={"id": key, "size": 4321, "content_type": "image/jpeg"},
        )
        row = self.row(key)
        self.assertEqual((row.status, row.size_bytes, row.content_type), (Status.ATTACHED, 4321, "image/jpeg"))
        self.assertIsNotNone(row.attached_at)

    def test_legacy_key_takes_branch_from_record(self):
        self.student_b.image_data = {"id": "2026/11/08/old.jpg", "size": 10}
        self.student_b.save()
        row = self.row("2026/11/08/old.jpg")
        self.assertEqual((row.branch_id, row.class_obj_id, row.category), (self.branch_b.pk, None, "students"))

    def test_replacing_image_deletes_old_and_attaches_new(self):
        old_key, new_key = self.class_key(), self.class_key()
        image = ActivityImage.objects.create(activity=self.activity, image_data={"id": old_key, "size": 100})
        with self.captureOnCommitCallbacks(execute=True):
            image.image_data = {"id": new_key, "size": 200}
            image.save()
        self.delete_object.assert_called_once_with(old_key)
        self.assertEqual(self.row(old_key).status, Status.DELETED)
        self.assertEqual(self.row(new_key).status, Status.ATTACHED)
        self.assertEqual(self.usage(self.branch_a), 200)

    def test_deleting_record_deletes_object(self):
        key = self.class_key()
        image = ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 100})
        with self.captureOnCommitCallbacks(execute=True):
            image.delete()
        self.assertEqual(self.row(key).status, Status.DELETED)
        self.assertIsNotNone(self.row(key).deleted_at)
        self.assertEqual(self.usage(self.branch_a), 0)

    def test_failed_storage_delete_keeps_row_counted(self):
        key = self.class_key()
        image = ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 100})
        self.delete_object.side_effect = RuntimeError("storage down")
        with self.captureOnCommitCallbacks(execute=True):
            image.delete()
        self.assertEqual(self.row(key).status, Status.ATTACHED)

    def test_shared_key_stays_attached_while_referenced(self):
        key = self.class_key()
        first = ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 100})
        ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 100})
        with self.captureOnCommitCallbacks(execute=True):
            first.delete()
        self.assertEqual(self.row(key).status, Status.ATTACHED)

    def test_rolled_back_save_leaves_no_row(self):
        key = self.class_key()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 100})
                raise RuntimeError("rollback")
        self.assertFalse(MediaObject.objects.filter(file_key=key).exists())

    def test_unchanged_key_does_not_touch_row(self):
        key = self.class_key()
        image = ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 100})
        MediaObject.objects.filter(file_key=key).update(size_bytes=999)
        image.caption = "edited"
        image.save()
        self.assertEqual(self.row(key).size_bytes, 999)


@patch("apps.uploads.management.commands.cleanup_orphaned_uploads.get_storage")
class CleanupTests(TrackingTestCase):
    def pending(self, key, age):
        row = MediaObject.objects.create(file_key=key, branch=self.branch_a, size_bytes=50)
        MediaObject.objects.filter(pk=row.pk).update(created_at=timezone.now() - age)

    def test_expired_unreferenced_pending_is_deleted(self, storage):
        self.pending("expired.jpg", timedelta(days=1))
        self.pending("fresh.jpg", timedelta(minutes=1))
        call_command("cleanup_orphaned_uploads", stdout=StringIO())
        storage.return_value.delete_object.assert_called_once_with("expired.jpg")
        self.assertEqual(self.row("expired.jpg").status, Status.DELETED)
        self.assertEqual(self.row("fresh.jpg").status, Status.PENDING)

    def test_expired_but_referenced_pending_becomes_attached(self, storage):
        key = self.class_key()
        ActivityImage.objects.create(activity=self.activity, image_data={"id": key})
        MediaObject.objects.filter(file_key=key).update(status=Status.PENDING, created_at=timezone.now() - timedelta(days=1))
        call_command("cleanup_orphaned_uploads", stdout=StringIO())
        storage.return_value.delete_object.assert_not_called()
        self.assertEqual(self.row(key).status, Status.ATTACHED)


class BackfillTests(TrackingTestCase):
    def setUp(self):
        super().setUp()
        self.class_image_key = self.class_key()
        ActivityImage.objects.create(activity=self.activity, image_data={"id": self.class_image_key, "size": 300})
        self.student_b.image_data = {"object_key": "2026/01/01/student.jpg", "metadata": {"size": 70}}
        self.student_b.save()
        self.school.image_data = {"id": "2026/01/01/logo.png"}
        self.school.save()
        # Pretend these were attached before tracking existed.
        MediaObject.objects.all().delete()

    def run_backfill(self, *args):
        out = StringIO()
        call_command("backfill_media_objects", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_without_writing(self):
        output = self.run_backfill("--dry-run")
        self.assertIn("Would track 3 file(s)", output)
        self.assertIn(f"branch {self.branch_a.pk}: 2 file(s), 300 bytes", output)
        self.assertFalse(MediaObject.objects.exists())

    def test_backfill_tracks_each_file_once(self):
        self.run_backfill()
        self.assertEqual(MediaObject.objects.filter(status=Status.ATTACHED).count(), 3)
        self.assertEqual(self.usage(self.branch_a), 300)
        self.assertEqual(self.usage(self.branch_b), 70)
        # A school logo on a legacy key counts against the school's first branch.
        self.assertEqual(self.row("2026/01/01/logo.png").branch_id, min(self.branch_a.pk, self.branch_b.pk))
        self.assertIn("Tracked 0 file(s); 3 already tracked", self.run_backfill())

    def test_missing_sizes_can_be_fetched_later(self):
        self.run_backfill()
        self.assertEqual(self.row("2026/01/01/logo.png").size_bytes, 0)
        with patch.object(MediaService, "_get_file_size", return_value=1234) as get_size:
            self.run_backfill("--fetch-missing-sizes")
        get_size.assert_called_once_with("2026/01/01/logo.png")
        self.assertEqual(self.row("2026/01/01/logo.png").size_bytes, 1234)


class ReconcileTests(TrackingTestCase):
    """--reconcile compares each branch_{id}/ folder with media_objects."""

    def setUp(self):
        super().setUp()
        from tempfile import TemporaryDirectory
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.media_root = tmp.name
        override = override_settings(STORAGE_TYPE="local", MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        StorageFactory.reset()
        self.addCleanup(StorageFactory.reset)

    def store(self, key, size=10, age=timedelta(days=1)):
        import os
        path = os.path.join(self.media_root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        stamp = (timezone.now() - age).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def reconcile(self, *args):
        out = StringIO()
        call_command("cleanup_orphaned_uploads", "--reconcile", *args, stdout=out)
        return out.getvalue()

    def test_lists_branch_folder(self):
        self.store(f"branch_{self.branch_a.pk}/students/a.jpg", size=7)
        self.store(f"branch_{self.branch_a.pk}/class_{self.class_a.pk}/activities/b.jpg", size=9)
        self.store(f"branch_{self.branch_b.pk}/students/c.jpg")
        listed = sorted((o.key, o.size) for o in StorageFactory.get_storage().list_objects(f"branch_{self.branch_a.pk}/"))
        self.assertEqual(listed, [
            (f"branch_{self.branch_a.pk}/class_{self.class_a.pk}/activities/b.jpg", 9),
            (f"branch_{self.branch_a.pk}/students/a.jpg", 7),
        ])

    def test_unreferenced_untracked_file_is_deleted(self):
        import os
        path = self.store(f"branch_{self.branch_a.pk}/students/orphan.jpg", size=40)
        output = self.reconcile()
        self.assertFalse(os.path.exists(path))
        row = self.row(f"branch_{self.branch_a.pk}/students/orphan.jpg")
        self.assertEqual((row.status, row.size_bytes, row.branch_id), (Status.DELETED, 40, self.branch_a.pk))
        self.assertIn("1 orphan(s) deleted", output)

    def test_recent_untracked_file_is_left_alone(self):
        import os
        path = self.store(f"branch_{self.branch_a.pk}/students/new.jpg", age=timedelta(minutes=1))
        self.reconcile()
        self.assertTrue(os.path.exists(path))
        self.assertFalse(MediaObject.objects.exists())

    def test_referenced_untracked_file_is_adopted(self):
        key = self.class_key()
        ActivityImage.objects.create(activity=self.activity, image_data={"id": key})
        MediaObject.objects.all().delete()
        self.store(key, size=55)
        self.reconcile()
        row = self.row(key)
        self.assertEqual(
            (row.status, row.size_bytes, row.branch_id, row.class_obj_id, row.category),
            (Status.ATTACHED, 55, self.branch_a.pk, self.class_a.pk, "activities"),
        )

    def test_tracked_size_is_corrected_and_missing_reported(self):
        key = self.class_key()
        ActivityImage.objects.create(activity=self.activity, image_data={"id": key, "size": 1})
        self.store(key, size=99)
        gone = self.class_key()
        ActivityImage.objects.create(activity=self.activity, image_data={"id": gone, "size": 5})
        with self.assertLogs("apps.uploads.management.commands.cleanup_orphaned_uploads", "WARNING"):
            output = self.reconcile()
        self.assertEqual(self.row(key).size_bytes, 99)
        self.assertEqual(self.row(gone).status, Status.ATTACHED)
        self.assertIn("1 size(s) corrected, 1 tracked file(s) missing", output)

    def test_dry_run_and_branch_filter_change_nothing_elsewhere(self):
        import os
        a = self.store(f"branch_{self.branch_a.pk}/students/a.jpg")
        b = self.store(f"branch_{self.branch_b.pk}/students/b.jpg")
        output = self.reconcile("--dry-run")
        self.assertIn("Would reconcile: 0 untracked file(s) adopted, 2 orphan(s) deleted", output)
        self.assertTrue(os.path.exists(a) and os.path.exists(b))
        self.assertFalse(MediaObject.objects.exists())

        self.reconcile("--branch", str(self.branch_b.pk))
        self.assertTrue(os.path.exists(a))
        self.assertFalse(os.path.exists(b))

    def test_branch_and_dry_run_need_reconcile(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("cleanup_orphaned_uploads", "--dry-run", stdout=StringIO())
