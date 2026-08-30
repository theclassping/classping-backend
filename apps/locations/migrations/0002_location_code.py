from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("locations", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE locations ADD COLUMN IF NOT EXISTS code VARCHAR(50);",
            reverse_sql="ALTER TABLE locations DROP COLUMN IF EXISTS code;",
        ),
    ]