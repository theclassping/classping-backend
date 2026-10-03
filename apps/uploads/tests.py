import os
from tempfile import TemporaryDirectory
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import patch
from apps.users.models import User

from apps.uploads.storage import LocalStorage


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
        response = self.client.get("/api/media/download/url/?file_key=file.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["url"], "https://download.test/file.jpg")

    @patch("apps.uploads.views.get_storage")
    def test_download_url_returns_404_for_missing_file(self, get_storage):
        get_storage.return_value.verify_object_exists.return_value = False
        response = self.client.get("/api/media/download/url/?file_key=missing.jpg")
        self.assertEqual(response.status_code, 404)
