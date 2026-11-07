"""Helpers for handling admin-web file uploads consistently with the API."""

import os
import tempfile

from django.conf import settings
from PIL import Image, ImageOps

from apps.uploads.services.media import MediaService
from apps.uploads.paths import media_key_for_instance
from apps.uploads.storage import get_storage, generate_file_key

# Same limits the school frontend applies before uploading (lib/imageResize.ts).
MAX_IMAGE_EDGE = 1600
IMAGE_QUALITY = 82
# Files already this small and within MAX_IMAGE_EDGE are stored untouched.
SKIP_BELOW_BYTES = 300 * 1024


def _jpeg_name(name):
    base = os.path.splitext(name)[0] or "image"
    return f"{base}.jpg"


def _shrink_image(path):
    """Downscale a photo into a JPEG next to path.

    Returns (stored_path, width, height); stored_path is path itself when the
    original is kept because it is already small or cannot be re-encoded.
    """
    try:
        with Image.open(path) as original:
            # Re-encoding an animated GIF would keep only its first frame.
            if original.format == "GIF":
                return path, original.width, original.height
            img = ImageOps.exif_transpose(original)
            width, height = img.size
            scale = min(1, MAX_IMAGE_EDGE / max(width, height))
            if scale == 1 and os.path.getsize(path) <= SKIP_BELOW_BYTES:
                return path, width, height
            if scale < 1:
                width, height = max(1, round(width * scale)), max(1, round(height * scale))
                img = img.resize((width, height), Image.LANCZOS)
            # JPEG has no alpha channel; paint white so transparent PNGs don't turn black.
            rgba = img.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, "white")
            flattened.paste(rgba, mask=rgba)
            output_path = f"{path}.jpg"
            flattened.save(output_path, "JPEG", quality=IMAGE_QUALITY, optimize=True)
    except Exception:
        return (path, *MediaService._get_image_dimensions(path))

    # Flat screenshots can compress better as PNG than JPEG; never store more bytes.
    if os.path.getsize(output_path) >= os.path.getsize(path):
        os.unlink(output_path)
        return (path, *MediaService._get_image_dimensions(path))
    return output_path, width, height


def process_uploaded_image(uploaded_file, instance=None):
    """Convert an uploaded file into the same metadata shape used by the API.

    With instance, the file is stored under that record's branch folder when
    the record already knows its branch; otherwise a legacy date key is used.
    """
    if not uploaded_file:
        return None

    suffix = os.path.splitext(uploaded_file.name)[1]
    temp_path = None
    stored_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name
        stored_path, width, height = _shrink_image(temp_path)
        if stored_path != temp_path:
            filename = _jpeg_name(uploaded_file.name)
            content_type = "image/jpeg"
        else:
            filename = uploaded_file.name
            content_type = uploaded_file.content_type

        extension = os.path.splitext(filename)[1].lower()
        file_key = (media_key_for_instance(instance, extension) if instance is not None else None) \
            or generate_file_key(filename)

        if getattr(settings, "STORAGE_TYPE", "local") == "r2":
            content_type = content_type or "application/octet-stream"
            storage = get_storage()
            with open(stored_path, "rb") as file_handle:
                storage.client.put_object(
                    Bucket=storage.bucket_name,
                    Key=file_key,
                    Body=file_handle,
                    ContentType=content_type,
                )
            # Everything the API reads back from R2 is already known here.
            metadata = {
                "id": file_key,
                "storage": "r2",
                "object_key": file_key,
                "content_type": content_type,
                "size": os.path.getsize(stored_path),
                "width": width,
                "height": height,
            }
        else:
            metadata = MediaService.store_local_file(stored_path, filename, content_type, object_key=file_key)
        metadata["filename"] = filename
        metadata["content_type"] = content_type or metadata.get("content_type")
        return metadata
    finally:
        for path in {temp_path, stored_path}:
            if path and os.path.exists(path):
                os.unlink(path)
