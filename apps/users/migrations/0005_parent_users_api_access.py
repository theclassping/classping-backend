from django.db import migrations


def grant_parent_users_access(apps, schema_editor):
    permission_model = apps.get_model("users", "RoleModulePermission")
    permission_model.objects.update_or_create(
        role="PARENT",
        module="users",
        defaults={
            "can_read": True,
            "can_create": True,
            "can_edit": True,
            "can_delete": True,
        },
    )


def revoke_parent_users_access(apps, schema_editor):
    permission_model = apps.get_model("users", "RoleModulePermission")
    permission_model.objects.filter(
        role="PARENT",
        module="users",
    ).update(
        can_read=False,
        can_create=False,
        can_edit=False,
        can_delete=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_rolemodulepermission"),
    ]

    operations = [
        migrations.RunPython(
            grant_parent_users_access,
            revoke_parent_users_access,
        ),
    ]
