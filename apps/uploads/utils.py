"""
Utilities for media fields in models.
Provides mixin and helper methods for accessing media URLs.
"""
import json
from typing import Optional, Dict, Any

from apps.uploads.services.media import MediaService


class MediaFieldMixin:
    """
    Mixin for models with media fields (image_data, profile_data, etc).
    
    Provides properties to access:
    - object.image_data  -> returns the JSON metadata dict
    - object.image_url   -> returns the full accessible URL
    
    Example:
        class ActivityImage(MediaFieldMixin, models.Model):
            image_data = models.JSONField(...)
        
        activity_img = ActivityImage.objects.first()
        activity_img.image_data  # Returns: {"id": "...", "storage": "r2", "metadata": {...}}
        activity_img.image_url   # Returns: "https://bucket.r2.cloudflarestorage.com/2025/01/15/abc123.png"
    """
    
    @staticmethod
    def _parse_media_data(media_field_value: Any) -> Optional[Dict[str, Any]]:
        """
        Parse media field value (could be string or dict).
        
        Args:
            media_field_value: Value from JSONField/TextField
        
        Returns:
            Parsed dict or None if invalid
        """
        if not media_field_value:
            return None
        
        if isinstance(media_field_value, dict):
            return media_field_value
        
        if isinstance(media_field_value, str):
            try:
                return json.loads(media_field_value)
            except (json.JSONDecodeError, TypeError):
                return None
        
        return None
    
    def get_image_url(self) -> Optional[str]:
        """
        Get the URL for image_data field.
        
        Returns:
            Full URL string or None if no image
        """
        if not hasattr(self, 'image_data'):
            return None
        
        media_data = self._parse_media_data(self.image_data)
        if not media_data:
            return None
        
        try:
            # media_data should be a dict with 'id' field
            return MediaService.get_object_url(media_data)
        except Exception:
            return None
    
    def get_profile_image_url(self) -> Optional[str]:
        """Get the URL for profile_image field."""
        if not hasattr(self, 'profile_image'):
            return None
        
        media_data = self._parse_media_data(self.profile_image)
        if not media_data:
            return None
        
        try:
            return MediaService.get_object_url(media_data)
        except Exception:
            return None
    
    def get_media_url(self, field_name: str) -> Optional[str]:
        """
        Generic method to get URL for any media field.
        
        Args:
            field_name: Name of the media field (e.g., 'image_data', 'profile_data')
        
        Returns:
            Full URL string or None if field doesn't exist or is empty
        """
        if not hasattr(self, field_name):
            return None
        
        media_data = self._parse_media_data(getattr(self, field_name))
        if not media_data:
            return None
        
        try:
            return MediaService.get_object_url(media_data)
        except Exception:
            return None
