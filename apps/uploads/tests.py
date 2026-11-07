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

        # No signed token can name a traversal key, so the request is refused.
        self.assertEqual(response.status_code, 403)


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
            {"filename": "photo.jpg", "content_type": "image/jpeg", "size": 1234},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content_type"], "image/jpeg")
        generate.assert_called_once_with(
            filename="photo.jpg", content_type="image/jpeg", size=1234,
            user_id=self.user.pk, expires_in=3600, location=None,
        )

    def test_presign_rejects_invalid_expiration(self):
        response = self.client.post(
            "/api/media/presign/",
            {"filename": "photo.jpg", "content_type": "image/jpeg", "size": 10, "expires_in": 10},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_presign_rejects_non_image_types(self):
        for content_type in ("application/pdf", "text/html", "image/svg+xml", "application/octet-stream"):
            response = self.client.post(
                "/api/media/presign/",
                {"filename": "file.jpg", "content_type": content_type, "size": 10},
                format="json",
            )
            self.assertEqual(response.status_code, 400, content_type)
            self.assertIn("content_type", response.data)

    def test_presign_requires_size_within_limit(self):
        with override_settings(MAX_UPLOAD_BYTES=1024):
            too_big = self.client.post(
                "/api/media/presign/",
                {"filename": "a.jpg", "content_type": "image/jpeg", "size": 1025},
                format="json",
            )
        missing = self.client.post(
            "/api/media/presign/",
            {"filename": "a.jpg", "content_type": "image/jpeg"},
            format="json",
        )
        self.assertEqual(too_big.status_code, 400)
        self.assertIn("size", too_big.data)
        self.assertEqual(missing.status_code, 400)
        self.assertIn("size", missing.data)

    def test_presign_key_extension_comes_from_content_type(self):
        from apps.uploads.services.media import MediaService
        with override_settings(SITE_URL="http://testserver"), \
                patch.object(MediaService, "_redis", return_value=None):
            result = MediaService.generate_presign_url(
                "evil.html", "image/png", size=10, user_id=self.user.pk,
            )
        self.assertTrue(result["file_key"].endswith(".png"))
        MediaService._pending_uploads.pop(result["file_key"], None)

    def test_upload_without_signed_token_is_rejected(self):
        with TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir):
                response = self.client.generic(
                    "PUT",
                    "/api/media/upload/photos/test.bin",
                    data=b"binary-content",
                    content_type="application/octet-stream",
                )
                self.assertEqual(response.status_code, 403)
                self.assertFalse(os.path.exists(os.path.join(tmpdir, "photos", "test.bin")))

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

    def test_upload_must_match_signed_type_and_size(self):
        with TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir, SITE_URL="http://testserver"):
                url = LocalStorage().generate_presigned_url(
                    "photos/signed.jpg", expires_in=60,
                    content_type="image/jpeg", content_length=len(b"binary-content"),
                ).replace("http://testserver", "")
                wrong_type = self.client.generic("PUT", url, data=b"binary-content", content_type="text/html")
                wrong_size = self.client.generic("PUT", url, data=b"binary-content-plus", content_type="image/jpeg")
                ok = self.client.generic("PUT", url, data=b"binary-content", content_type="image/jpeg")
        self.assertEqual(wrong_type.status_code, 403)
        self.assertEqual(wrong_size.status_code, 403)
        self.assertEqual(ok.status_code, 204)

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
        pipe = redis.return_value.pipeline.return_value
        with self.captureOnCommitCallbacks(execute=True):
            self.create_owner({"id": "attached.jpg"})
            pipe.zrem.assert_not_called()
        pipe.zrem.assert_called_once_with("classping:uploads:pending", "attached.jpg")
        pipe.delete.assert_called_once_with("classping:upload:attached.jpg")
        pipe.execute.assert_called_once_with()

    @patch("apps.uploads.services.media.MediaService._redis")
    @patch("apps.uploads.management.commands.cleanup_orphaned_uploads.get_storage")
    def test_cleanup_preserves_referenced_files_including_legacy_metadata(self, storage, redis):
        from django.core.management import call_command
        from io import StringIO

        self.create_owner({"id": "attached.jpg"})
        # Older metadata named the key only under object_key. (Rows stored as
        # JSON strings are converted by uploads migration 0002.)
        self.create_owner({"object_key": "legacy.jpg"})
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

        storage.return_value.bucket_name = "bucket"
        with override_settings(STORAGE_TYPE="r2"):
            metadata = MediaService._describe_object("2026/11/01/photo.png", None)

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

        storage.return_value.bucket_name = "bucket"
        pending = {"user_id": "1", "content_type": "image/jpeg"}
        with override_settings(STORAGE_TYPE="r2", MAX_UPLOAD_BYTES=10 * 1024 * 1024):
            with self.assertRaisesMessage(FileTooLargeError, "Maximum size is 10 MB"):
                MediaService._describe_object("2026/11/02/huge.jpg", pending)
        client.get_object.assert_not_called()
        # A rejected new upload is removed instead of lingering in the bucket.
        storage.return_value.delete_object.assert_called_once_with("2026/11/02/huge.jpg")

    @patch("apps.uploads.services.media.get_storage")
    def test_new_upload_with_non_image_type_is_deleted(self, storage):
        from apps.uploads.services.media import MediaInputError, MediaService
        client = storage.return_value.client
        client.head_object.return_value = {"ContentType": "text/html", "ContentLength": 10}
        with override_settings(STORAGE_TYPE="r2"):
            with self.assertRaisesMessage(MediaInputError, "Unsupported file type"):
                MediaService._describe_object("2026/11/02/page.jpg", {"user_id": "1"})
        client.get_object.assert_not_called()
        storage.return_value.delete_object.assert_called_once_with("2026/11/02/page.jpg")

    @patch("apps.uploads.services.media.get_storage")
    def test_missing_r2_object_is_reported_as_not_found(self, storage):
        from botocore.exceptions import ClientError
        from apps.uploads.services.media import MediaService
        storage.return_value.client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject",
        )
        with override_settings(STORAGE_TYPE="r2"):
            with self.assertRaises(FileNotFoundError):
                MediaService._describe_object("2026/11/02/gone.jpg", None)

    def test_extract_key_accepts_keys_dicts_and_urls(self):
        from apps.uploads.services.media import MediaInputError, MediaService
        with override_settings(R2_BUCKET_NAME="bucket", MEDIA_URL="/media/"):
            for value in (
                "2026/11/02/a.jpg",
                {"id": "2026/11/02/a.jpg"},
                {"object_key": "2026/11/02/a.jpg"},
                "https://bucket.acct.r2.cloudflarestorage.com/2026/11/02/a.jpg?X-Amz-Signature=x",
                "https://acct.r2.cloudflarestorage.com/bucket/2026/11/02/a.jpg",
                "http://localhost:8000/media/2026/11/02/a.jpg",
            ):
                self.assertEqual(MediaService.extract_key(value), "2026/11/02/a.jpg", value)
            for value in ("", {}, 42, "/etc/passwd", "../secret"):
                with self.assertRaises(MediaInputError):
                    MediaService.extract_key(value)


class ImageOwnershipTests(TestCase):
    """Only the uploader, or someone who can already see the image, may attach a key."""

    def setUp(self):
        from apps.uploads.services.media import MediaService
        self.MediaService = MediaService
        self.owner = User.objects.create_user(
            email="owner@example.com", password="StrongPassword123!", role=User.Role.ADMIN,
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="StrongPassword123!", role=User.Role.ADMIN,
        )
        MediaService._pending_uploads.clear()
        MediaService._pending_uploads["2026/11/03/mine.jpg"] = {
            "user_id": str(self.owner.pk), "content_type": "image/jpeg", "filename": "mine.jpg",
        }
        # Use the in-process pending store even if REDIS_URL is set locally.
        patch.object(MediaService, "_redis", return_value=None).start()
        self.describe = patch.object(
            MediaService, "_describe_object",
            side_effect=lambda key, pending: {"id": key, "object_key": key, "pending": bool(pending)},
        ).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(MediaService._pending_uploads.clear)

    def test_uploader_can_attach_pending_key(self):
        metadata = self.MediaService.resolve_image_data("2026/11/03/mine.jpg", self.owner)
        self.assertEqual(metadata["id"], "2026/11/03/mine.jpg")
        self.assertTrue(metadata["pending"])

    def test_other_user_cannot_attach_someone_elses_pending_key(self):
        with self.assertRaises(FileNotFoundError):
            self.MediaService.resolve_image_data("2026/11/03/mine.jpg", self.other)

    def test_unknown_key_is_not_found_even_if_it_exists_in_storage(self):
        with self.assertRaises(FileNotFoundError):
            self.MediaService.resolve_image_data({"id": "2026/11/03/someone-elses.jpg"}, self.owner)
        self.describe.assert_not_called()

    def test_key_already_on_a_visible_record_can_be_sent_again(self):
        Student.objects.create(
            first_name="Seen", last_name="Before", date_of_birth="2018-01-01",
            gender="other", enroll_date="2026-07-01", image_data={"id": "2026/11/03/existing.jpg"},
        )
        metadata = self.MediaService.resolve_image_data({"id": "2026/11/03/existing.jpg"}, self.other)
        self.assertFalse(metadata["pending"])

    def test_anonymous_user_cannot_attach(self):
        from django.contrib.auth.models import AnonymousUser
        with self.assertRaises(FileNotFoundError):
            self.MediaService.resolve_image_data("2026/11/03/mine.jpg", AnonymousUser())

    def test_payment_proof_dict_goes_through_ownership_check(self):
        from rest_framework.test import APIRequestFactory
        from apps.payments.serializers import PaymentProofSerializer
        request = APIRequestFactory().post("/")
        request.user = self.other
        serializer = PaymentProofSerializer(context={"request": request})
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            serializer.validate_image_data({"id": "2026/11/03/mine.jpg", "storage": "r2"})
        request.user = self.owner
        self.assertEqual(
            serializer.validate_image_data({"id": "2026/11/03/mine.jpg"})["id"],
            "2026/11/03/mine.jpg",
        )


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


class MediaReferenceLookupTests(TestCase):
    """is_media_referenced asks the database instead of loading every row."""

    def create_student(self, image_data):
        return Student.objects.create(
            first_name="Ref", last_name="Owner", date_of_birth="2018-01-01",
            gender="other", enroll_date="2026-07-01", image_data=image_data,
        )

    def test_finds_key_under_id_or_object_key(self):
        from apps.uploads.references import is_media_referenced
        self.create_student({"id": "2026/11/07/by-id.jpg"})
        self.create_student({"object_key": "2026/11/07/by-object-key.jpg"})
        self.assertTrue(is_media_referenced("2026/11/07/by-id.jpg"))
        self.assertTrue(is_media_referenced("2026/11/07/by-object-key.jpg"))
        self.assertFalse(is_media_referenced("2026/11/07/unused.jpg"))

    def test_query_count_does_not_grow_with_rows(self):
        from apps.uploads.references import MEDIA_MODELS, is_media_referenced
        for i in range(20):
            self.create_student({"id": f"2026/11/07/{i}.jpg"})
        # One EXISTS query per media table, however many rows there are.
        with self.assertNumQueries(len(MEDIA_MODELS)):
            self.assertFalse(is_media_referenced("2026/11/07/unused.jpg"))

    def test_migration_turns_json_strings_into_objects(self):
        import importlib
        from django.apps import apps as django_apps
        from apps.uploads.references import is_media_referenced
        migration = importlib.import_module("apps.uploads.migrations.0002_normalize_image_data")

        legacy = self.create_student('{"id": "2026/11/07/legacy.jpg"}')
        plain = self.create_student("not json")
        normal = self.create_student({"id": "2026/11/07/normal.jpg"})
        self.assertFalse(is_media_referenced("2026/11/07/legacy.jpg"))

        migration.normalize_image_data(django_apps, None)

        for row in (legacy, plain, normal):
            row.refresh_from_db()
        self.assertEqual(legacy.image_data, {"id": "2026/11/07/legacy.jpg"})
        self.assertEqual(plain.image_data, "not json")
        self.assertEqual(normal.image_data, {"id": "2026/11/07/normal.jpg"})
        self.assertTrue(is_media_referenced("2026/11/07/legacy.jpg"))

    def test_download_access_matches_object_key_only_records(self):
        from apps.core.access import user_can_access_media
        admin = User.objects.create_user(
            email="ref-admin@example.com", password="StrongPassword123!", role=User.Role.ADMIN,
        )
        self.create_student({"object_key": "2026/11/07/old-style.jpg"})
        self.assertTrue(user_can_access_media(admin, "2026/11/07/old-style.jpg"))

    def test_lookup_can_use_the_image_data_key_indexes(self):
        from django.db import connection
        from apps.uploads.references import media_key_filter
        if connection.vendor != "postgresql":
            self.skipTest("expression indexes are checked on PostgreSQL")
        queryset = Student._base_manager.filter(media_key_filter("2026/11/07/x.jpg"))
        with connection.cursor() as cursor:
            # Tiny test tables are cheaper to scan, so make the planner show
            # whether it *can* use the indexes for this exact filter.
            cursor.execute("SET LOCAL enable_seqscan = off")
            plan = queryset.explain()
        self.assertIn("students_media_id", plan)
        self.assertIn("students_media_key", plan)


class RedisClientTests(SimpleTestCase):
    """One shared client per process, and no silent fallback once Redis is configured."""

    def setUp(self):
        from apps.uploads.services.media import MediaService
        self.MediaService = MediaService
        MediaService._redis_client = None
        self.addCleanup(setattr, MediaService, "_redis_client", None)

    def test_no_client_without_redis_url(self):
        with override_settings(REDIS_URL=""):
            self.assertIsNone(self.MediaService._redis())

    def test_client_is_reused_and_never_pinged(self):
        with patch("redis.Redis.from_url") as from_url, \
                override_settings(REDIS_URL="redis://cache:6379/0"):
            first = self.MediaService._redis()
            second = self.MediaService._redis()
        self.assertIs(first, second)
        from_url.assert_called_once()
        first.ping.assert_not_called()
        kwargs = from_url.call_args.kwargs
        self.assertEqual(kwargs["socket_timeout"], self.MediaService.REDIS_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["socket_connect_timeout"], self.MediaService.REDIS_TIMEOUT_SECONDS)

    def test_new_client_when_redis_url_changes(self):
        with patch("redis.Redis.from_url", side_effect=lambda *a, **k: mock.Mock()) as from_url:
            with override_settings(REDIS_URL="redis://one:6379/0"):
                first = self.MediaService._redis()
            with override_settings(REDIS_URL="redis://two:6379/0"):
                second = self.MediaService._redis()
        self.assertIsNot(first, second)
        self.assertEqual(from_url.call_count, 2)

    def down_client(self):
        import redis
        client = mock.Mock()
        client.get.side_effect = redis.ConnectionError("down")
        client.pipeline.return_value.execute.side_effect = redis.ConnectionError("down")
        return client

    def test_presign_fails_instead_of_using_process_memory(self):
        from apps.uploads.services.media import UploadStoreUnavailable
        self.MediaService._pending_uploads.clear()
        with patch.object(self.MediaService, "_redis", return_value=self.down_client()), \
                override_settings(SITE_URL="http://testserver"):
            with self.assertRaises(UploadStoreUnavailable):
                self.MediaService.generate_presign_url("a.jpg", "image/jpeg", size=10, user_id=1)
        self.assertEqual(self.MediaService._pending_uploads, {})

    def test_attach_returns_503_when_redis_is_down(self):
        from apps.uploads.serializers import ServiceUnavailable, resolve_image_input
        serializer = mock.Mock(context={"request": mock.Mock(user=mock.Mock(pk=1))})
        with patch.object(self.MediaService, "_redis", return_value=self.down_client()):
            with self.assertRaises(ServiceUnavailable) as caught:
                resolve_image_input(serializer, "2026/11/07/a.jpg")
        self.assertEqual(caught.exception.status_code, 503)


class PresignRedisOutageTests(TestCase):
    def test_presign_endpoint_returns_503(self):
        import redis
        from apps.uploads.services.media import MediaService
        user = User.objects.create_user(
            email="presign-503@example.com", password="StrongPassword123!", role=User.Role.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        down = mock.Mock()
        down.pipeline.return_value.execute.side_effect = redis.ConnectionError("down")
        with patch.object(MediaService, "_redis", return_value=down):
            response = client.post(
                "/api/media/presign/",
                {"filename": "a.jpg", "content_type": "image/jpeg", "size": 10},
                format="json",
            )
        self.assertEqual(response.status_code, 503)
