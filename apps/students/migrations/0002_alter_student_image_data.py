"""
Migration for Student model.
Removes old image_data field and creates new JSONField.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0001_initial'),
    ]

    operations = [
        # Remove the old TextField
        migrations.RemoveField(
            model_name='student',
            name='image_data',
        ),
        # Add the new JSONField
        migrations.AddField(
            model_name='student',
            name='image_data',
            field=models.JSONField(
                blank=True,
                default=None,
                help_text='Stores media metadata: {id, storage, metadata: {filename, size, mime_type}}',
                null=True,
            ),
        ),
    ]
