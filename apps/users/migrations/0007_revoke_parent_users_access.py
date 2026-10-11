from django.db import migrations


def revoke_parent_users_access(apps, schema_editor):
    permission_model = apps.get_model("users", "RoleModulePermission")
    permission_model.objects.filter(role="PARENT", module="users").update(
        can_read=False,
        can_create=False,
        can_edit=False,
        can_delete=False,
    )


class Migration(migrations.Migration):
    dependencies = [("users", "0006_merge_20261004_1023")]
    operations = [
        migrations.RunPython(revoke_parent_users_access, migrations.RunPython.noop),
    ]
