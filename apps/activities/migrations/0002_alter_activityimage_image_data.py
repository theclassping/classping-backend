"""
Migration for ActivityImage model.
Removes old image_data field and creates new JSONField.
"""
from django.db import migrations, models


def create_activity_join_tables(apps, schema_editor):
    """Create tables moved from removed apps when bootstrapping a new DB."""
    existing_tables = set(schema_editor.connection.introspection.table_names())

    for model_name in ("ActivityImage", "ActivityStudent"):
        model = apps.get_model("activities", model_name)
        if model._meta.db_table not in existing_tables:
            schema_editor.create_model(model)


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0002_merge_activity_images_students'),
    ]

    operations = [
        migrations.RunPython(
            create_activity_join_tables,
            migrations.RunPython.noop,
        ),
        # Remove the old ImageField
        migrations.RemoveField(
            model_name='activityimage',
            name='image_data',
        ),
        # Add the new JSONField
        migrations.AddField(
            model_name='activityimage',
            name='image_data',
            field=models.JSONField(
                blank=True,
                default=None,
                help_text='Stores media metadata: {id, storage, metadata: {filename, size, mime_type}}',
                null=True,
            ),
        ),
    ]
