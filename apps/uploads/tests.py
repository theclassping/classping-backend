import os
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import quote

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import patch
from apps.users.models import User
from apps.students.models import Student

from apps.uploads.storage import LocalStorage, make_upload_token


class LocalStorageSecurityTests(SimpleTestCase):
    @override_settings(MEDIA_ROOT="/tmp/classping-test-media")
    def test_verify_object_exists_rejects_path_traversal(self):
        with TemporaryDirectory() as tmpdir:
            settings.MEDIA_ROOT = tmpdir
            outside_path = os.path.join(os.path.dirname(tmpdir), "escaped_secret.txt")
            with open(outside_path, "wb") as handle:
                handle.write(b"secret")

            self.assertFalse(LocalStorage().verify_object_exists("../escaped_secret.txt"))

    @override_settings(MEDIA_ROOT="/tmp/classping-test-media")
    def test_generate_presigned_url_uses_safe_upload_url(self):
        with TemporaryDirectory() as tmpdir:
            settings.MEDIA_ROOT = tmpdir
            with self.assertRaises(ValueError):
                LocalStorage().generate_presigned_url("../../escape.txt")

    def test_upload_api_rejects_path_traversal(self):
        from rest_framework.test import APIRequestFactory, force_authenticate

        from apps.uploads.views import UploadView

        request = APIRequestFactory().put(
            "/api/media/upload/../../escape.txt",
            b"secret",
            content_type="application/octet-stream",
        )
        force_authenticate(request, user=mock.Mock(is_authenticated=True))

        response = UploadView.as_view()(request, file_key="../../escape.txt")

        self.assertEqual(response.status_code, 400)


class MediaApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="media-api@example.com",
            password="StrongPassword123!",
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("apps.uploads.views.MediaService.generate_presign_url")
    def test_presign_success(self, generate):
        generate.return_value = {
            "file_key": "2026/10/photo.jpg",
            "presigned_url": "http://testserver/api/media/upload/2026/10/photo.jpg?method=PUT",
            "expires_in": 3600,
            "content_type": "image/jpeg",
        }
        response = self.client.post(
            "/api/media/presign/",
            {"filename": "photo.jpg", "content_type": "image/jpeg"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content_type"], "image/jpeg")

    def test_presign_rejects_invalid_expiration(self):
        response = self.client.post(
            "/api/media/presign/",
            {"filename": "photo.jpg", "content_type": "image/jpeg", "expires_in": 10},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(MEDIA_ROOT="/tmp/classping-media-api")
    def test_upload_success_writes_binary_content(self):
        with TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir):
                response = self.client.generic(
                    "PUT",
                    "/api/media/upload/photos/test.bin",
                    data=b"binary-content",
                    content_type="application/octet-stream",
                )
                self.assertEqual(response.status_code, 204)
                with open(os.path.join(tmpdir, "photos", "test.bin"), "rb") as handle:
                    self.assertEqual(handle.read(), b"binary-content")

    @patch("apps.uploads.views.get_storage")
    def test_download_url_returns_url_for_existing_file(self, get_storage):
        get_storage.return_value.verify_object_exists.return_value = True
        get_storage.return_value.generate_presigned_download_url.return_value = "https://download.test/file.jpg"
        Student.objects.create(
            first_name="Media",
            last_name="Owner",
            date_of_birth="2018-01-01",
            gender="other",
            enroll_date="2026-07-01",
            image_data={"id": "file.jpg"},
        )
        response = self.client.get("/api/media/download/url/?file_key=file.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["url"], "https://download.test/file.jpg")

    @patch("apps.uploads.views.get_storage")
    def test_download_url_returns_404_for_missing_file(self, get_storage):
        get_storage.return_value.verify_object_exists.return_value = False
        response = self.client.get("/api/media/download/url/?file_key=missing.jpg")
        self.assertEqual(response.status_code, 404)


class SignedUploadTokenTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _put(self, file_key, token):
        return self.client.generic(
            "PUT",
            f"/api/media/upload/{file_key}?token={quote(token, safe='')}",
            data=b"binary-content",
            content_type="application/octet-stream",
        )

    def test_presigned_local_url_uploads_without_jwt(self):
        with TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir, SITE_URL="http://testserver"):
                url = LocalStorage().generate_presigned_url("photos/signed.bin", expires_in=60)
                response = self.client.generic(
                    "PUT",
                    url.replace("http://testserver", ""),
                    data=b"binary-content",
                    content_type="application/octet-stream",
                )
                self.assertEqual(response.status_code, 204)
                with open(os.path.join(tmpdir, "photos", "signed.bin"), "rb") as handle:
                    self.assertEqual(handle.read(), b"binary-content")

    def test_token_for_another_key_is_rejected(self):
        token = make_upload_token("photos/allowed.bin", expires_in=60)
        self.assertEqual(self._put("photos/other.bin", token).status_code, 401)

    def test_expired_token_is_rejected(self):
        token = make_upload_token("photos/expired.bin", expires_in=-1)
        self.assertEqual(self._put("photos/expired.bin", token).status_code, 401)

    def test_tampered_token_is_rejected(self):
        token = make_upload_token("photos/tampered.bin", expires_in=60)
        self.assertEqual(self._put("photos/tampered.bin", token + "x").status_code, 401)


class UploadCleanupTests(TestCase):
    def create_owner(self, data):
        return Student.objects.create(
            first_name="Upload", last_name="Owner", date_of_birth="2018-01-01",
            gender="other", enroll_date="2026-07-01", image_data=data,
        )

    @patch("apps.uploads.services.media.MediaService._redis")
    def test_pending_cleared_only_after_commit(self, redis):
        with self.captureOnCommitCallbacks(execute=True):
            self.create_owner({"id": "attached.jpg"})
            redis.return_value.zrem.assert_not_called()
        redis.return_value.zrem.assert_called_once_with(
            "classping:uploads:pending", "attached.jpg"
        )

    @patch("apps.uploads.services.media.MediaService._redis")
    @patch("apps.uploads.management.commands.cleanup_orphaned_uploads.get_storage")
    def test_cleanup_preserves_referenced_files_including_legacy_metadata(self, storage, redis):
        import json
        from django.core.management import call_command
        from io import StringIO

        self.create_owner({"id": "attached.jpg"})
        self.create_owner(json.dumps({"object_key": "legacy.jpg"}))
        redis.return_value.zrangebyscore.return_value = [
            "attached.jpg", "legacy.jpg", "orphan.jpg",
        ]
        call_command("cleanup_orphaned_uploads", stdout=StringIO())
        storage.return_value.delete_object.assert_called_once_with("orphan.jpg")

    @patch("apps.uploads.services.media.MediaService._redis")
    @patch("apps.uploads.management.commands.cleanup_orphaned_uploads.get_storage")
    def test_failed_delete_keeps_pending_entry_for_retry(self, storage, redis):
        from django.core.management import call_command
        redis.return_value.zrangebyscore.return_value = ["orphan.jpg"]
        storage.return_value.delete_object.side_effect = RuntimeError("storage unavailable")
        with self.assertRaises(RuntimeError):
            call_command("cleanup_orphaned_uploads")
        redis.return_value.zrem.assert_not_called()

    @patch("apps.uploads.signals.MediaService.delete_object")
    def test_shared_media_is_preserved_when_owner_deleted(self, delete):
        first = self.create_owner({"id": "shared.jpg"})
        self.create_owner({"id": "shared.jpg"})
        with self.captureOnCommitCallbacks(execute=True):
            first.delete()
        delete.assert_not_called()

    def test_cleanup_schedule_removed_from_persistent_store_at_start(self):
        from apscheduler.events import EVENT_SCHEDULER_STARTED
        from apps.student_invoices.scheduler import register_jobs, SCHEDULED_JOBS
        scheduler = mock.Mock()
        register_jobs(scheduler)
        self.assertNotIn("cleanup_orphaned_uploads", [job["id"] for job in SCHEDULED_JOBS])
        callback, event = scheduler.add_listener.call_args.args
        self.assertEqual(event, EVENT_SCHEDULER_STARTED)
        callback(None)
        scheduler.remove_job.assert_called_once_with("cleanup_orphaned_uploads")

    @patch("apps.uploads.services.media.MediaService._redis")
    def test_rolled_back_save_keeps_pending_state(self, redis):
        from django.db import transaction
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    self.create_owner({"id": "rolled-back.jpg"})
                    raise RuntimeError("rollback")
        redis.assert_not_called()

    @patch("apps.uploads.services.media.MediaService._redis", return_value=None)
    @patch("apps.uploads.management.commands.cleanup_orphaned_uploads.get_storage")
    def test_cleanup_without_redis_does_not_access_storage(self, storage, redis):
        from django.core.management import call_command
        from io import StringIO
        call_command("cleanup_orphaned_uploads", stdout=StringIO())
        storage.assert_not_called()


class MediaServiceDownloadAndDimensionTests(SimpleTestCase):
    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    @patch("apps.uploads.services.media.get_storage")
    def test_download_url_is_reused_while_cached(self, storage):
        from django.core.cache import cache
        from apps.uploads.services.media import MediaService
        cache.clear()
        storage.return_value.generate_presigned_download_url.side_effect = ["https://r2.test/a", "https://r2.test/b"]

        first = MediaService.generate_download_url("photo.jpg")
        second = MediaService.get_object_url({"object_key": "photo.jpg"})

        self.assertEqual(first, "https://r2.test/a")
        self.assertEqual(second, "https://r2.test/a")
        storage.return_value.generate_presigned_download_url.assert_called_once_with(
            file_key="photo.jpg", expires_in=3600,
        )

    @patch("apps.uploads.services.media.get_storage")
    def test_r2_dimensions_read_only_file_header(self, storage):
        import io
        from PIL import Image
        from apps.uploads.services.media import MediaService
        png = io.BytesIO()
        Image.new("RGB", (40, 30)).save(png, "PNG")
        client = storage.return_value.client
        client.head_object.return_value = {"ContentType": "image/png", "ContentLength": 5_000_000}
        client.get_object.return_value = {"Body": io.BytesIO(png.getvalue())}

        with override_settings(R2_BUCKET_NAME="bucket"):
            metadata = MediaService._process_r2_image("2026/11/01/photo.png")

        self.assertEqual((metadata["width"], metadata["height"]), (40, 30))
        self.assertEqual(metadata["size"], 5_000_000)
        client.get_object.assert_called_once_with(
            Bucket="bucket", Key="2026/11/01/photo.png",
            Range=f"bytes=0-{MediaService.DIMENSION_PROBE_BYTES - 1}",
        )

    @patch("apps.uploads.services.media.get_storage")
    def test_oversized_r2_upload_is_rejected_without_download(self, storage):
        from apps.uploads.services.media import FileTooLargeError, MediaService
        client = storage.return_value.client
        client.head_object.return_value = {"ContentType": "image/jpeg", "ContentLength": 11 * 1024 * 1024}

        with override_settings(R2_BUCKET_NAME="bucket", MAX_UPLOAD_BYTES=10 * 1024 * 1024):
            with self.assertRaisesMessage(FileTooLargeError, "Maximum size is 10 MB"):
                MediaService._process_r2_image("2026/11/02/huge.jpg")
        client.get_object.assert_not_called()


@override_settings(STORAGE_TYPE="r2")
class AdminWebImageUploadTests(SimpleTestCase):
    def upload(self, name, size, fmt, content_type, noise=True):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)) if noise else Image.new("RGB", size, "white")
        data = io.BytesIO()
        img.save(data, fmt)
        return SimpleUploadedFile(name, data.getvalue(), content_type=content_type)

    @patch("apps.admin_web.media.get_storage")
    def test_large_photo_is_shrunk_and_not_read_back_from_r2(self, storage):
        from apps.admin_web.media import process_uploaded_image
        stored = {}
        storage.return_value.bucket_name = "bucket"
        storage.return_value.client.put_object.side_effect = lambda **kw: stored.update(kw, body=kw["Body"].read())

        metadata = process_uploaded_image(self.upload("photo.png", (2400, 1200), "PNG", "image/png"))

        self.assertEqual((metadata["width"], metadata["height"]), (1600, 800))
        self.assertEqual(metadata["filename"], "photo.jpg")
        self.assertEqual(metadata["content_type"], "image/jpeg")
        self.assertEqual(metadata["size"], len(stored["body"]))
        self.assertTrue(stored["Key"].endswith(".jpg"))
        self.assertEqual(stored["ContentType"], "image/jpeg")
        storage.return_value.client.get_object.assert_not_called()
        storage.return_value.client.head_object.assert_not_called()

    @patch("apps.admin_web.media.get_storage")
    def test_small_photo_is_stored_untouched(self, storage):
        from apps.admin_web.media import process_uploaded_image
        storage.return_value.bucket_name = "bucket"
        upload = self.upload("logo.png", (200, 100), "PNG", "image/png", noise=False)

        metadata = process_uploaded_image(upload)

        self.assertEqual((metadata["width"], metadata["height"]), (200, 100))
        self.assertEqual(metadata["filename"], "logo.png")
        self.assertEqual(metadata["content_type"], "image/png")
        self.assertEqual(metadata["size"], upload.size)
