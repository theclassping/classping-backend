# State-only migration: ActivityImage/ActivityStudent tables already exist
# (created previously under the now-removed activity_images/activity_students apps).
# This just re-registers their model state under the "activities" app label.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0001_initial'),
        ('students', '0003_alter_student_table_alter_studentguardian_table'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='ActivityImage',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('image_data', models.ImageField(upload_to='activities/images/')),
                        ('caption', models.TextField(blank=True)),
                        ('activity', models.ForeignKey(db_column='activity_id', on_delete=django.db.models.deletion.CASCADE, related_name='images', to='activities.activity')),
                        ('student', models.ForeignKey(blank=True, db_column='student_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activity_images', to='students.student')),
                    ],
                    options={
                        'db_table': 'activity_images',
                    },
                ),
                migrations.CreateModel(
                    name='ActivityStudent',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('activity', models.ForeignKey(db_column='activity_id', on_delete=django.db.models.deletion.CASCADE, related_name='activity_students', to='activities.activity')),
                        ('student', models.ForeignKey(db_column='student_id', on_delete=django.db.models.deletion.CASCADE, related_name='activity_assignments', to='students.student')),
                    ],
                    options={
                        'db_table': 'activity_students',
                    },
                ),
                migrations.AddConstraint(
                    model_name='activitystudent',
                    constraint=models.UniqueConstraint(fields=('activity', 'student'), name='unique_activity_student'),
                ),
            ],
            database_operations=[],
        ),
    ]
