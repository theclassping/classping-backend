from django.db import models

from apps.locations.models import Location
from apps.uploads.utils import MediaFieldMixin


class School(models.Model, MediaFieldMixin):
    name = models.CharField(max_length=255)
    register_number = models.CharField(max_length=50, unique=True)
    image_data = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Stores media metadata: {id, storage, object_key, filename, content_type, size, width, height}"
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "schools"

    def __str__(self):
        return self.name
    
    @property
    def image_url(self):
        """Get the full URL to access the image."""
        return self.get_image_url()
    
class Branch(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="branches",
    )

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="branches",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "school_branches"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_branch_code_per_school",
            )
        ]

    def __str__(self):
        return f"{self.school.name} - {self.name}"