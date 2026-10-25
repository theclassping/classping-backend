from django.db import migrations


def enable_student_creation(apps, schema_editor):
    permission = apps.get_model("users", "RoleModulePermission")
    permission.objects.filter(role="TEACHER", module="students").update(can_create=True)


class Migration(migrations.Migration):
    dependencies = [("users", "0008_revokedtokensession")]
    operations = [migrations.RunPython(enable_student_creation, migrations.RunPython.noop)]
