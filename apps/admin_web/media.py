"""Helpers for handling admin-web file uploads consistently with the API."""

import os
import tempfile

from apps.uploads.services.media import MediaService


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
        metadata = MediaService.process_image_data(temp_path)
        metadata["filename"] = uploaded_file.name
        metadata["content_type"] = uploaded_file.content_type or metadata.get("content_type")
        return metadata
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
