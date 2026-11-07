"""
Media service for handling upload operations.
Manages presigned URLs, metadata, and file processing.
"""
import json
import os
import mimetypes
from typing import Dict, Any, Optional
from datetime import datetime
from urllib.parse import unquote, urlparse
from PIL import Image
import io
import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.cache import cache

from apps.uploads.storage import get_storage, generate_file_key, validate_file_key

logger = logging.getLogger(__name__)

# Only images may be uploaded through the API. The value is the extension
# used for the stored key, so the client's filename never picks it.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


class MediaInputError(ValueError):
    """Raised when client-supplied image_data cannot be attached to a record."""


class FileTooLargeError(MediaInputError):
    """Raised when a stored upload is bigger than settings.MAX_UPLOAD_BYTES."""


class UploadStoreUnavailable(RuntimeError):
    """Raised when REDIS_URL is set but Redis cannot be reached.

    Pending uploads must be visible to every worker, so there is no silent
    fallback to per-process memory once Redis is configured.
    """


class MediaService:
    """Service for managing media uploads and metadata."""

    # Development store, used only when REDIS_URL is not configured. It is
    # per process, so it is only correct with a single worker (runserver).
    _pending_uploads: Dict[str, Dict[str, Any]] = {}

    # One Redis client per process, as (url, client). redis-py keeps a
    # connection pool inside the client and resets it after a fork.
    _redis_client = None

    # Fail fast instead of hanging a request when Redis is unreachable.
    REDIS_TIMEOUT_SECONDS = 2

    # Phone JPEGs can carry ~100 KB of EXIF/ICC data before the size marker.
    DIMENSION_PROBE_BYTES = 256 * 1024

    # Reuse a download URL until this many seconds before it expires, so
    # clients see the same URL and can cache the image.
    DOWNLOAD_URL_REFRESH_MARGIN = 600

    @classmethod
    def _redis(cls):
        """
        Return the shared Redis client, or None when REDIS_URL is not set.

        Creating the client doesn't connect; a Redis outage shows up as a
        redis.RedisError from the command that needs it, which callers turn
        into UploadStoreUnavailable via _redis_call().
        """
        redis_url = getattr(settings, "REDIS_URL", "")
        if not redis_url:
            return None
        cached = cls._redis_client
        if cached is None or cached[0] != redis_url:
            import redis
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=cls.REDIS_TIMEOUT_SECONDS,
                socket_timeout=cls.REDIS_TIMEOUT_SECONDS,
                health_check_interval=30,
            )
            cls._redis_client = cached = (redis_url, client)
        return cached[1]

    @classmethod
    def _redis_call(cls, operation):
        """Run operation(client) and report a Redis outage as UploadStoreUnavailable."""
        import redis
        try:
            return operation(cls._redis())
        except redis.RedisError as error:
            logger.exception("Redis unavailable for upload tracking")
            raise UploadStoreUnavailable("Upload service is temporarily unavailable.") from error

    @classmethod
    def _upload_cache_key(cls, file_key: str) -> str:
        return f"classping:upload:{file_key}"

    @classmethod
    def _pending_uploads_key(cls) -> str:
        return "classping:uploads:pending"

    @classmethod
    def generate_presign_url(
        cls,
        filename: str,
        content_type: str,
        size: int,
        user_id: Any,
        expires_in: int = 3600
    ) -> Dict[str, Any]:
        """
        Generate a presigned URL for client to upload file.

        The URL is signed for exactly this content type and byte size, and the
        pending upload remembers who asked for it so only that user can attach
        the file to a record.

        Returns:
            {
                "file_key": "2025/01/15/abc123def456.jpg",
                "presigned_url": "https://...",
                "expires_in": 3600,
                "content_type": "image/jpeg"
            }
        """
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise MediaInputError("Unsupported file type.")
        cls._check_file_size(size)

        storage = get_storage()
        file_key = generate_file_key(filename, extension=ALLOWED_IMAGE_TYPES[content_type])

        # The pending entry is what lets the user attach the file, so the URL
        # must not outlive it.
        expires_in = min(int(expires_in), settings.UPLOAD_METADATA_TTL)
        presigned_url = storage.generate_presigned_url(
            file_key,
            expires_in,
            content_type=content_type,
            content_length=size,
        )

        upload_info = {
            'filename': filename,
            'content_type': content_type,
            'size': size,
            'user_id': str(user_id),
            'file_key': file_key,
            'created_at': datetime.now().isoformat(),
            'status': 'pending'
        }
        if cls._redis():
            def save_pending(client):
                # MULTI/EXEC: the metadata and the cleanup entry are written
                # together, so an upload is never attachable but untracked.
                pipe = client.pipeline(transaction=True)
                pipe.setex(
                    cls._upload_cache_key(file_key),
                    settings.UPLOAD_METADATA_TTL,
                    json.dumps(upload_info),
                )
                pipe.zadd(
                    cls._pending_uploads_key(),
                    {file_key: datetime.now().timestamp() + settings.UPLOAD_METADATA_TTL},
                )
                pipe.execute()
            cls._redis_call(save_pending)
        else:
            cls._pending_uploads[file_key] = upload_info

        return {
            'file_key': file_key,
            'presigned_url': presigned_url,
            'expires_in': expires_in,
            'content_type': content_type,
        }

    @classmethod
    def _get_pending(cls, file_key: str) -> Optional[Dict[str, Any]]:
        if cls._redis():
            raw_info = cls._redis_call(lambda client: client.get(cls._upload_cache_key(file_key)))
            return json.loads(raw_info) if raw_info else None
        return cls._pending_uploads.get(file_key)

    @classmethod
    def generate_download_url(
        cls,
        file_key: str,
        expires_in: int = 3600,
    ) -> str:
        cache_key = f"classping:download-url:{expires_in}:{file_key}"
        try:
            url = cache.get(cache_key)
        except Exception:
            logger.warning("Download URL cache unavailable", exc_info=True)
            url = None
        if url:
            return url

        url = get_storage().generate_presigned_download_url(
            file_key=file_key,
            expires_in=expires_in,
        )
        ttl = expires_in - cls.DOWNLOAD_URL_REFRESH_MARGIN
        if ttl > 0:
            try:
                cache.set(cache_key, url, ttl)
            except Exception:
                logger.warning("Download URL cache unavailable", exc_info=True)
        return url

    @classmethod
    def complete_upload(
        cls,
        file_key: str,
        file_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Mark an upload as complete and verify the file exists.

        Args:
            file_key: The file key from presign response
            file_size: File size in bytes (optional, will be fetched)

        Returns:
            {
                "id": "file_key",
                "storage": "r2" or "local",
                "metadata": {
                    "filename": "logo-1.png",
                    "size": 70389,
                    "mime_type": "image/png"
                }
            }
        """
        storage = get_storage()

        # Verify file exists in storage
        if not storage.verify_object_exists(file_key):
            raise FileNotFoundError(f"File not found in storage: {file_key}")

        # Get pending upload info from Redis, with a local fallback.
        redis_client = cls._redis()
        if redis_client:
            raw_info = redis_client.getdel(cls._upload_cache_key(file_key))
            redis_client.zrem(cls._pending_uploads_key(), file_key)
            upload_info = json.loads(raw_info) if raw_info else {}
        else:
            upload_info = cls._pending_uploads.pop(file_key, {})

        filename = upload_info.get('filename', 'unknown')
        content_type = upload_info.get('content_type', 'application/octet-stream')

        # Get file size if available
        if file_size is None:
            file_size = cls._get_file_size(file_key)

        # Build metadata
        metadata = {
            'filename': filename,
            'size': file_size,
            'mime_type': content_type,
        }

        # Determine storage type
        storage_type = 'r2' if settings.STORAGE_TYPE == 'r2' else 'local'

        # Return complete media metadata
        return {
            'id': file_key,
            'storage': storage_type,
            'metadata': metadata,
        }

    @classmethod
    def mark_upload_attached(cls, file_key: str) -> None:
        """Clear pending state after the owning database transaction commits."""
        if cls._redis():
            def clear_pending(client):
                pipe = client.pipeline(transaction=True)
                pipe.zrem(cls._pending_uploads_key(), file_key)
                pipe.delete(cls._upload_cache_key(file_key))
                pipe.execute()
            cls._redis_call(clear_pending)
        cls._pending_uploads.pop(file_key, None)

    @classmethod
    def get_object_url(cls, media_data: Dict[str, Any]) -> str:
        """
        Get the full accessible URL for a media object.

        Args:
            media_data: The media metadata dict containing 'id'

        Returns:
            Full URL to access the file
        """
        file_key = media_data.get('id') or media_data.get('object_key')

        if not file_key:
            raise ValueError("media_data must contain 'id' field")

        return cls.generate_download_url(file_key)

    @classmethod
    def _get_file_size(cls, file_key: str) -> int:
        """Get file size from storage backend."""
        storage_type = getattr(settings, 'STORAGE_TYPE', 'local')

        if storage_type == 'r2':
            try:
                s3_client = boto3.client(
                    's3',
                    endpoint_url=f'https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
                    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                    region_name=settings.R2_REGION,
                )
                response = s3_client.head_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=file_key
                )
                return response.get('ContentLength', 0)
            except Exception:
                return 0
        else:
            file_path = os.path.join(settings.MEDIA_ROOT, file_key)
            if os.path.exists(file_path):
                return os.path.getsize(file_path)
            return 0

    @classmethod
    def cancel_upload(cls, file_key: str) -> bool:
        """Cancel a pending upload."""
        if file_key in cls._pending_uploads:
            del cls._pending_uploads[file_key]
            return True
        return False

    @classmethod
    def delete_object(cls, file_key: str) -> None:
        """Delete a completed object from the configured storage backend."""
        get_storage().delete_object(file_key)

    @classmethod
    def extract_key(cls, value: Any) -> str:
        """Return the storage key from a key, a storage/media URL or a metadata dict."""
        if isinstance(value, dict):
            value = value.get("id") or value.get("object_key")
        if not isinstance(value, str) or not value.strip():
            raise MediaInputError("Invalid image_data.")

        value = value.strip()
        if value.startswith(("http://", "https://")):
            path = unquote(urlparse(value).path).lstrip("/")
            # Path-style R2 URLs and local media URLs carry a prefix before the key.
            for prefix in (f"{settings.R2_BUCKET_NAME}/", settings.MEDIA_URL.lstrip("/")):
                if prefix and path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            value = path

        try:
            return validate_file_key(value)
        except ValueError:
            raise MediaInputError("Invalid image_data.")

    @classmethod
    def resolve_image_data(cls, value: Any, user) -> Dict[str, Any]:
        """
        Turn client-supplied image_data into the metadata stored on a record.

        A key may be attached only when:
        - this user created it through presign and it is still pending, or
        - it already belongs to a record this user can see (the same image
          sent again on update, or a retried save).

        Anything else, including keys copied from another school's image URL,
        is reported as not found so the caller learns nothing about the key.
        """
        key = cls.extract_key(value)
        user_id = getattr(user, "pk", None)
        if user_id is None:
            raise FileNotFoundError("File not found.")

        pending = cls._get_pending(key)
        if pending and str(pending.get("user_id")) == str(user_id):
            return cls._describe_object(key, pending)

        from apps.core.access import user_can_access_media
        if user_can_access_media(user, key):
            return cls._describe_object(key, None)

        raise FileNotFoundError("File not found.")

    @classmethod
    def _check_file_size(cls, file_size: int) -> None:
        limit = settings.MAX_UPLOAD_BYTES
        if file_size > limit:
            raise FileTooLargeError(
                f"File is too large. Maximum size is {limit // (1024 * 1024)} MB."
            )

    @classmethod
    def _reject_upload(cls, key: str, error: MediaInputError):
        """Delete a new upload that broke the rules so it doesn't linger in storage."""
        try:
            cls.delete_object(key)
        except Exception:
            logger.exception("Unable to delete rejected upload %s", key)
        cls.mark_upload_attached(key)
        raise error

    @classmethod
    def _describe_object(cls, key: str, pending: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Read a stored object's metadata. New uploads (pending is set) must be
        an allowed image type within the size limit; files already attached
        to a record are described as they are.
        """
        if getattr(settings, "STORAGE_TYPE", "local") == "r2":
            content_type, file_size, width, height = cls._read_r2_object(key, enforce=bool(pending))
            storage_type = "r2"
        else:
            content_type, file_size, width, height = cls._read_local_object(key, pending)
            storage_type = "local"

        if pending:
            if content_type not in ALLOWED_IMAGE_TYPES:
                cls._reject_upload(key, MediaInputError("Unsupported file type."))
            try:
                cls._check_file_size(file_size)
            except FileTooLargeError as error:
                cls._reject_upload(key, error)

        return {
            "id": key,
            "storage": storage_type,
            "object_key": key,
            "filename": (pending or {}).get("filename") or key.split("/")[-1],
            "content_type": content_type,
            "size": file_size,
            "width": width,
            "height": height,
        }

    @classmethod
    def _read_r2_object(cls, key: str, enforce: bool) -> tuple:
        storage = get_storage()
        s3_client = storage.client
        try:
            response = s3_client.head_object(Bucket=storage.bucket_name, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                raise FileNotFoundError("File not found.")
            raise

        content_type = response.get("ContentType", "application/octet-stream")
        file_size = response.get("ContentLength", 0)
        # Don't download anything from an upload that is about to be rejected.
        if enforce and (content_type not in ALLOWED_IMAGE_TYPES or file_size > settings.MAX_UPLOAD_BYTES):
            return content_type, file_size, 0, 0

        # Image headers sit at the start of the file, so fetch only that part
        # instead of pulling the whole photo into memory.
        width, height = 0, 0
        try:
            file_obj = s3_client.get_object(
                Bucket=storage.bucket_name,
                Key=key,
                Range=f'bytes=0-{cls.DIMENSION_PROBE_BYTES - 1}',
            )
            width, height = cls._get_image_dimensions_from_bytes(file_obj['Body'].read())
        except Exception:
            pass  # If we can't read dimensions, just skip
        return content_type, file_size, width, height

    @classmethod
    def _read_local_object(cls, key: str, pending: Optional[Dict[str, Any]]) -> tuple:
        media_root = os.path.abspath(settings.MEDIA_ROOT)
        file_path = os.path.abspath(os.path.join(media_root, key))
        if os.path.commonpath([media_root, file_path]) != media_root or not os.path.isfile(file_path):
            raise FileNotFoundError("File not found.")

        # Local uploads were checked against the signed type when they were PUT.
        content_type = (pending or {}).get("content_type") or mimetypes.guess_type(file_path)[0]
        width, height = cls._get_image_dimensions(file_path)
        return content_type or "application/octet-stream", os.path.getsize(file_path), width, height

    @classmethod
    def store_local_file(cls, file_path: str, filename: str, content_type: Optional[str]) -> Dict[str, Any]:
        """
        Copy a server-side file into local media storage.

        Only for files the server produced itself (admin-web uploads); never
        pass a path that came from a client.
        """
        import shutil

        file_size = os.path.getsize(file_path)
        cls._check_file_size(file_size)

        object_key = generate_file_key(filename)
        dest_path = os.path.join(settings.MEDIA_ROOT, object_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(file_path, dest_path)
        width, height = cls._get_image_dimensions(dest_path)

        return {
            "id": object_key,
            "storage": "local",
            "object_key": object_key,
            "filename": filename,
            "content_type": content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "size": file_size,
            "width": width,
            "height": height,
        }

    @classmethod
    def _get_image_dimensions(cls, file_path: str) -> tuple:
        """Get image width and height from file."""
        try:
            with Image.open(file_path) as img:
                return img.width, img.height
        except Exception:
            return 0, 0

    @classmethod
    def _get_image_dimensions_from_bytes(cls, image_bytes: bytes) -> tuple:
        """Get image width and height from bytes."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            return img.width, img.height
        except Exception:
            return 0, 0
