"""Database indexes for finding records by the file key in image_data."""
from django.db import models
from django.db.models.fields.json import KeyTransform


def media_key_indexes(table):
    """
    Index image_data's "id" and "object_key" so is_media_referenced() and
    user_can_access_media() don't scan the whole table.

    The expression (image_data -> 'id') is exactly what the
    image_data__id=<key> lookup in media_key_filter() compiles to on
    PostgreSQL, so the planner can use these indexes for that filter.
    """
    return [
        models.Index(KeyTransform("id", "image_data"), name=f"{table}_media_id"),
        models.Index(KeyTransform("object_key", "image_data"), name=f"{table}_media_key"),
    ]
