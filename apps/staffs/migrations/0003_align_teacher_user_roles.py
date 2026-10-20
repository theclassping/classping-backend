from django.db import migrations


def align_teacher_roles(apps, schema_editor):
    Staff = apps.get_model("staffs", "Staff")
    User = apps.get_model("users", "User")
    teacher_user_ids = Staff.objects.filter(
        staff_type="teacher",
        user__role="STAFF",
    ).values_list("user_id", flat=True)
    User.objects.filter(pk__in=teacher_user_ids).update(role="TEACHER")


class Migration(migrations.Migration):
    dependencies = [
        ("staffs", "0002_staff_user"),
        ("users", "0006_merge_20261004_1023"),
    ]

    operations = [
        migrations.RunPython(align_teacher_roles, migrations.RunPython.noop),
    ]
