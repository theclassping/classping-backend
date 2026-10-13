from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("students", "0006_alter_student_status"),
        ("schools", "0004_remove_branch_location_id_branch_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="students",
                to="schools.branch",
            ),
        ),
    ]
