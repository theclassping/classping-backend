"""
Media service for handling upload operations.
Manages presigned URLs, metadata, and file processing.
"""
import json
import os
import mimetypes
from typing import Dict, Any, Optional
from datetime import datetime
from PIL import Image
import io

import boto3
from django.conf import settings
from django.contrib.messages import storage

from apps.uploads.storage import get_storage, generate_file_key


class MediaService:
    """Service for managing media uploads and metadata."""
    
    # Map to store pending uploads (in-memory cache)
    # In production, use Redis or database
    _pending_uploads: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def generate_presign_url(
        cls,
        filename: str,
        content_type: str,
        expires_in: int = 3600
    ) -> Dict[str, Any]:
        """
        Generate a presigned URL for client to upload file.
        
        Args:
            filename: Original filename
            content_type: MIME type of file
            expires_in: Expiration time in seconds
        
        Returns:
            {
                "file_key": "2025/01/15/abc123def456.png",
                "presigned_url": "https://...",
                "expires_in": 3600,
                "content_type": "image/png"
            }
        """
        storage = get_storage()
        
        # Generate unique file key
        file_key = generate_file_key(filename)
        
        # Generate presigned URL
        presigned_url = storage.generate_presigned_url(file_key, expires_in)
        
        # Store upload metadata for later completion
        cls._pending_uploads[file_key] = {
            'filename': filename,
            'content_type': content_type,
            'file_key': file_key,
            'created_at': datetime.now().isoformat(),
            'status': 'pending'
        }
        
        return {
            'file_key': file_key,
            'presigned_url': presigned_url,
            'expires_in': expires_in,
            'content_type': content_type,
        }
    
    @classmethod
    def generate_download_url(
        cls,
        file_key: str,
        expires_in: int = 3600,
    ) -> str:
        storage = get_storage()

        return storage.generate_presigned_download_url(
            file_key=file_key,
            expires_in=expires_in,
        )
        
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
        
        # Get pending upload info
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
    def get_object_url(cls, media_data: Dict[str, Any]) -> str:
        """
        Get the full accessible URL for a media object.
        
        Args:
            media_data: The media metadata dict containing 'id'
        
        Returns:
            Full URL to access the file
        """
        storage = get_storage()
        file_key = media_data.get('id')
        
        if not file_key:
            raise ValueError("media_data must contain 'id' field")
        
        return storage.get_object_url(file_key)
    
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
            import os
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
    def process_image_data(cls, image_data_input: str) -> Dict[str, Any]:
        """
        Process image_data input (file path for local, URL for R2).
        
        For LOCAL: Reads file from filesystem, copies to media/, returns metadata
        For R2: Validates file exists in R2, reads metadata, returns metadata
        
        Args:
            image_data_input: 
                - Local: "C:/path/to/file.jpg" or "/path/to/file.jpg"
                - R2: "https://bucket.r2.cloudflarestorage.com/media/uuid" or "media/uuid"
        
        Returns:
            {
                "id": "object_key",
                "storage": "local|r2",
                "object_key": "media/uuid",
                "filename": "file.jpg",
                "content_type": "image/jpeg",
                "size": 245871,
                "width": 1200,
                "height": 800
            }
        """
        storage_type = getattr(settings, 'STORAGE_TYPE', 'local')
        
        if storage_type == 'r2':
            return cls._process_r2_image(image_data_input)
        else:
            return cls._process_local_image(image_data_input)
    
    @classmethod
    def _process_local_image(cls, file_path: str) -> Dict[str, Any]:
        """Process image from local filesystem."""
        import shutil
        from pathlib import Path
        
        # Validate file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Read file info
        filename = os.path.basename(file_path)
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'application/octet-stream'
        
        file_size = os.path.getsize(file_path)
        
        # Generate object key
        object_key = generate_file_key(filename)
        
        # Copy file to media folder
        dest_path = os.path.join(settings.MEDIA_ROOT, object_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(file_path, dest_path)
        
        # Get image dimensions
        width, height = cls._get_image_dimensions(dest_path)
        
        return {
            "id": object_key,
            "storage": "local",
            "object_key": object_key,
            "filename": filename,
            "content_type": content_type,
            "size": file_size,
            "width": width,
            "height": height,
        }
    
    @classmethod
    def _process_r2_image(cls, image_url_or_key: str) -> Dict[str, Any]:
        """Process image from R2 storage."""
        import re
        from urllib.parse import urlparse
        
        # Extract object key from URL or use as-is
        if image_url_or_key.startswith('http'):
            # Extract path from URL: https://bucket.r2.../media/uuid -> media/uuid
            parsed = urlparse(image_url_or_key)
            object_key = parsed.path.lstrip('/')
        else:
            object_key = image_url_or_key
        
        # Initialize R2 client
        s3_client = boto3.client(
            's3',
            endpoint_url=f'https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name=settings.R2_REGION,
        )
        
        # Verify file exists and get metadata
        try:
            response = s3_client.head_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=object_key
            )
        except s3_client.exceptions.NoSuchKey:
            raise FileNotFoundError(f"File not found in R2: {object_key}")
        except Exception as e:
            raise Exception(f"Error accessing R2: {str(e)}")
        
        # Extract metadata
        content_type = response.get('ContentType', 'application/octet-stream')
        file_size = response.get('ContentLength', 0)
        filename = object_key.split('/')[-1]
        
        # Try to get image dimensions from R2
        width, height = 0, 0
        try:
            file_obj = s3_client.get_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=object_key
            )
            width, height = cls._get_image_dimensions_from_bytes(
                file_obj['Body'].read()
            )
        except Exception:
            pass  # If we can't read dimensions, just skip
        
        return {
            "id": object_key,
            "storage": "r2",
            "object_key": object_key,
            "filename": filename,
            "content_type": content_type,
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
