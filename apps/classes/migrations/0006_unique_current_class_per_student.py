from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classes", "0005_alter_classstudent_student_related_name"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="classstudent",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_current=True),
                fields=("student",),
                name="unique_current_class_per_student",
            ),
        ),
    ]
