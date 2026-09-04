# Generated migration to change ClassStudent.student related_name

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classes', '0004_classstudent_is_current'),
        ('students', '0004_student_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='classstudent',
            name='student',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, 
                related_name='class_students', 
                to='students.student'
            ),
        ),
    ]
