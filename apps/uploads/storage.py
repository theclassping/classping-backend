"""
Storage abstraction layer for media uploads.
Supports both local storage and Cloudflare R2.
"""
import os
import uuid
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import boto3
from django.conf import settings


class StorageBackend(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    def generate_presigned_url(self, file_key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for uploading a file."""
        pass
    
    @abstractmethod
    def get_object_url(self, file_key: str) -> str:
        """Get the full URL for accessing an object."""
        pass
    
    @abstractmethod
    def verify_object_exists(self, file_key: str) -> bool:
        """Verify if an object exists in storage."""
        pass


class R2Storage(StorageBackend):
    """Cloudflare R2 storage backend."""
    
    def __init__(self):
        self.bucket_name = settings.R2_BUCKET_NAME
        self.account_id = settings.R2_ACCOUNT_ID
        self.access_key = settings.R2_ACCESS_KEY_ID
        self.secret_key = settings.R2_SECRET_ACCESS_KEY
        self.region = settings.R2_REGION
        
        # Initialize S3 client for R2
        self.client = boto3.client(
            's3',
            endpoint_url=f'https://{self.account_id}.r2.cloudflarestorage.com',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )
    
    def generate_presigned_url(self, file_key: str, expires_in: int = 3600) -> str:
        """Generate a presigned PUT URL for uploading to R2."""
        url = self.client.generate_presigned_url(
            'put_object',
            Params={'Bucket': self.bucket_name, 'Key': file_key},
            ExpiresIn=expires_in,
        )
        return url
    
    def get_object_url(self, file_key: str) -> str:
        """Get the full public URL for accessing an object in R2."""
        return f'https://{self.bucket_name}.{self.account_id}.r2.cloudflarestorage.com/{file_key}'
    
    def verify_object_exists(self, file_key: str) -> bool:
        """Verify if an object exists in R2."""
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=file_key)
            return True
        except self.client.exceptions.NoSuchKey:
            return False
        except Exception:
            return False


class LocalStorage(StorageBackend):
    """Local file system storage backend (development/testing)."""
    
    def __init__(self):
        self.media_root = settings.MEDIA_ROOT
        self.media_url = settings.MEDIA_URL
    
    def generate_presigned_url(self, file_key: str, expires_in: int = 3600) -> str:
        """For local storage, return the upload endpoint URL."""
        # In production, this would be a signed URL
        # For local dev, return a simple POST endpoint
        return f"{settings.SITE_URL}/api/media/upload/{file_key}"
    
    def get_object_url(self, file_key: str) -> str:
        """Get the full URL for accessing a local file."""
        return f"{settings.SITE_URL}{self.media_url}{file_key}"
    
    def verify_object_exists(self, file_key: str) -> bool:
        """Verify if a local file exists."""
        file_path = os.path.join(self.media_root, file_key)
        return os.path.exists(file_path)


class StorageFactory:
    """Factory to get the appropriate storage backend based on environment."""
    
    _instance: Optional[StorageBackend] = None
    
    @classmethod
    def get_storage(cls) -> StorageBackend:
        """Get storage backend singleton."""
        if cls._instance is None:
            storage_type = getattr(settings, 'STORAGE_TYPE', 'local')
            
            if storage_type == 'r2':
                cls._instance = R2Storage()
            else:
                cls._instance = LocalStorage()
        
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset the singleton (useful for testing)."""
        cls._instance = None


def get_storage() -> StorageBackend:
    """Convenience function to get storage backend."""
    return StorageFactory.get_storage()


def generate_file_key(original_filename: str) -> str:
    """
    Generate a unique file key with directory structure.
    Format: {year}/{month}/{day}/{uuid}_{filename}
    """
    import hashlib
    from datetime import datetime
    
    now = datetime.now()
    
    # Create unique ID from UUID and filename hash
    file_ext = os.path.splitext(original_filename)[1]
    unique_id = f"{uuid.uuid4().hex}"
    
    # Build path
    path = f"{now.year}/{now.month:02d}/{now.day:02d}/{unique_id}{file_ext}"
    return path
