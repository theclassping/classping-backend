from django.conf import settings
from django.db import models

from apps.uploads.utils import MediaFieldMixin


class Guardian(models.Model, MediaFieldMixin):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardian",
    )

    name = models.CharField(max_length=150)

    phone_number = models.CharField(
        max_length=30,
        blank=True,
        null=True,
    )

    email = models.EmailField(
        blank=True,
        null=True,
    )

    image_data = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Stores media metadata: {id, storage, object_key, filename, content_type, size, width, height}"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "guardians"

    def __str__(self):
        return self.name
    
    @property
    def image_url(self):
        """Get the full URL to access the image."""
        return self.get_image_url()