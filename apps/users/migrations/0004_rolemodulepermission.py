from django.db import migrations, models


MODULES = (
    "academic_years",
    "activities",
    "assessments",
    "classes",
    "fee_types",
    "guardians",
    "locations",
    "payments",
    "schools",
    "staffs",
    "student_invoices",
    "students",
    "uploads",
    "users",
)
TEACHER_READ_MODULES = (
    "academic_years",
    "activities",
    "classes",
    "students",
    "uploads",
)
PARENT_READ_MODULES = (
    "activities",
    "payments",
    "student_invoices",
    "uploads",
)


def seed_role_permissions(apps, schema_editor):
    permission_model = apps.get_model("users", "RoleModulePermission")

    for module in MODULES:
        permission_model.objects.create(
            role="ADMIN",
            module=module,
            can_read=True,
            can_create=True,
            can_edit=True,
            can_delete=True,
        )

        permission_model.objects.create(
            role="STAFF",
            module=module,
            can_read=(module != "users"),
            can_create=(module not in ("users", "schools")),
            can_edit=(module not in ("users", "schools")),
            can_delete=False,
        )

        permission_model.objects.create(
            role="TEACHER",
            module=module,
            can_read=(module in TEACHER_READ_MODULES),
            can_create=(module == "uploads"),
            can_edit=False,
            can_delete=False,
        )

        permission_model.objects.create(
            role="PARENT",
            module=module,
            can_read=(module in PARENT_READ_MODULES),
            can_create=(module in ("payments", "uploads")),
            can_edit=False,
            can_delete=False,
        )

    permission_model.objects.filter(
        role="TEACHER",
        module="activities",
    ).update(can_create=True, can_edit=True, can_delete=True)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_alter_user_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoleModulePermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("ADMIN", "Admin"), ("STAFF", "Staff"), ("TEACHER", "Teacher"), ("PARENT", "Parent")], max_length=20)),
                ("module", models.CharField(choices=[("academic_years", "Academic years"), ("activities", "Activities"), ("assessments", "Assessments"), ("classes", "Classes"), ("fee_types", "Fee types"), ("guardians", "Guardians"), ("locations", "Locations"), ("payments", "Payments"), ("schools", "Schools"), ("staffs", "Staff"), ("student_invoices", "Student invoices"), ("students", "Students"), ("uploads", "Media uploads"), ("users", "Users")], max_length=40)),
                ("can_read", models.BooleanField(default=False)),
                ("can_create", models.BooleanField(default=False)),
                ("can_edit", models.BooleanField(default=False)),
                ("can_delete", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ("role", "module"),
            },
        ),
        migrations.AddConstraint(
            model_name="rolemodulepermission",
            constraint=models.UniqueConstraint(fields=("role", "module"), name="unique_role_module_permission"),
        ),
        migrations.RunPython(seed_role_permissions, migrations.RunPython.noop),
    ]