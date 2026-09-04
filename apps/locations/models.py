from django.db import models
from mptt.models import MPTTModel
from mptt.fields import TreeForeignKey


class Location(MPTTModel):
    TYPE_CHOICES = [
        ("COUNTRY", "Country"),
        ("PROVINCE", "Province"),
        ("CITY", "City"),
        ("DISTRICT", "District"),
        ("VILLAGE", "Village"),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )
    # Column is "type" in the database.
    location_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_column="type")

    # Column is "parent_id" (matches Django's default FK column naming), populated by MPTT.
    parent = TreeForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        db_table = "locations"

    def __str__(self):
        return self.name

