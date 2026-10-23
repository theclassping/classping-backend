from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0007_account_management_permissions")]

    operations = [
        migrations.CreateModel(
            name="RevokedTokenSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sid", models.CharField(max_length=255, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
