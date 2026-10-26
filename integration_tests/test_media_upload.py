"""Real files uploaded through the presign flow into local storage."""
import io
import os
import shutil
import tempfile
from urllib.parse import urlsplit

from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.uploads.storage import StorageFactory

from .base import GUARDIAN_EMAIL, IntegrationTestCase


def jpeg_bytes(color):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="JPEG")
    return buffer.getvalue()


class MediaUploadFlowTests(IntegrationTestCase):
    def setUp(self):
        media_root = tempfile.mkdtemp(prefix="classping-media-")
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        settings_override = override_settings(
            STORAGE_TYPE="local",
            MEDIA_ROOT=media_root,
            REDIS_URL="",
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        # The storage backend is a singleton; rebuild it for these settings.
        StorageFactory.reset()
        self.addCleanup(StorageFactory.reset)
        self.media_root = media_root

        super().setUp()
        self.school = self.create_new_school()
        self.guardian_client, _ = self.login(GUARDIAN_EMAIL)

    def upload(self, client, filename, content):
        """Presign as the given user, then PUT the bytes like a browser would."""
        presign = self.post(client, "/api/media/presign/", {
            "filename": filename,
            "content_type": "image/jpeg",
        }, expected=200)
        url = urlsplit(presign["presigned_url"])
        # The browser uploads straight to the signed URL without a JWT.
        response = APIClient().put(
            f"{url.path}?{url.query}", content, content_type="image/jpeg",
        )
        self.assert_status(response, 204)

        file_key = presign["file_key"]
        with open(os.path.join(self.media_root, file_key), "rb") as stored:
            self.assertEqual(stored.read(), content)
        return {
            "id": file_key,
            "object_key": file_key,
            "storage": "local",
            "filename": filename,
            "content_type": "image/jpeg",
            "size": len(content),
        }

    def download_status(self, client, file_key):
        return client.get("/api/media/download/url/", {"file_key": file_key}).status_code

    def test_payment_proof_upload(self):
        school = self.school
        self.bill_class(school["staff_client"], school["branch_id"], school["class_id"])
        invoice_id = self.guardian_client.get("/api/student-invoices/").data[0]["id"]

        image_data = self.upload(self.guardian_client, "transfer.jpg", jpeg_bytes("green"))
        payment = self.post(self.guardian_client, "/api/payments/", {
            "student_invoice_id": invoice_id,
            "amount": "250000.00",
            "payment_method": "bank_transfer",
            "proofs": [{"image_data": image_data}],
        })
        self.assertIsNotNone(payment["proofs"][0]["image_url"])

        # Staff reviewing the payment, and the payer, can open the proof.
        self.assertEqual(self.download_status(school["staff_client"], image_data["id"]), 200)
        self.assertEqual(self.download_status(self.guardian_client, image_data["id"]), 200)

        # A staff member of another school cannot.
        other = self.create_new_school("harapan", guardian_email="guardian@harapan.test")
        self.assertEqual(self.download_status(other["staff_client"], image_data["id"]), 404)

    def test_activity_photo_upload_is_visible_to_tagged_child_only(self):
        school = self.school
        ayu = school["student"]
        bima = self.create_student(
            school["staff_client"], school["class_id"], "Bima", "Saputra", "bima.parent@example.com",
        )
        teacher_client = school["teacher_client"]
        image_data = self.upload(teacher_client, "ayu-painting.jpg", jpeg_bytes("blue"))

        activity = self.post(teacher_client, "/api/activities/", {
            "class_teacher_id": school["class_teacher_id"],
            "class_id": school["class_id"],
            "name": "Painting Day",
            "activity_date": str(timezone.localdate()),
            "is_publish": True,
            "student_ids": [ayu["id"], bima["id"]],
            "activity_images": [{"student_id": ayu["id"], "image_data": image_data}],
        })
        self.assertIsNotNone(activity["activity_images"][0]["image_url"])

        self.assertEqual(self.download_status(self.guardian_client, image_data["id"]), 200)
        bima_client, _ = self.login("bima.parent@example.com")
        self.assertEqual(self.download_status(bima_client, image_data["id"]), 404)
