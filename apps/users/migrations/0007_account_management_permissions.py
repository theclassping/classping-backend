from django.db import migrations


def update_permissions(apps, schema_editor):
    permission = apps.get_model("users", "RoleModulePermission")
    for role in ("STAFF", "TEACHER", "PARENT"):
        permission.objects.update_or_create(
            role=role, module="users",
            defaults={
                "can_read": True,
                "can_create": role != "PARENT",
                "can_edit": True,
                "can_delete": False,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("users", "0006_merge_20261004_1023")]
    operations = [migrations.RunPython(update_permissions, migrations.RunPython.noop)]
