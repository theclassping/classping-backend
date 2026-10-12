"""Helpers for handling admin-web file uploads consistently with the API."""

import os
import tempfile

from django.conf import settings

from apps.uploads.services.media import MediaService
from apps.uploads.storage import get_storage, generate_file_key


def process_uploaded_image(uploaded_file):
    """Convert an uploaded file into the same metadata shape used by the API."""
    if not uploaded_file:
        return None

    suffix = os.path.splitext(uploaded_file.name)[1]
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name
        if getattr(settings, "STORAGE_TYPE", "local") == "r2":
            file_key = generate_file_key(uploaded_file.name)
            storage = get_storage()
            with open(temp_path, "rb") as file_handle:
                storage.client.put_object(
                    Bucket=storage.bucket_name,
                    Key=file_key,
                    Body=file_handle,
                    ContentType=uploaded_file.content_type or "application/octet-stream",
                )
            metadata = MediaService.process_image_data(file_key)
        else:
            metadata = MediaService.process_image_data(temp_path)
        metadata["filename"] = uploaded_file.name
        metadata["content_type"] = uploaded_file.content_type or metadata.get("content_type")
        return metadata
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
