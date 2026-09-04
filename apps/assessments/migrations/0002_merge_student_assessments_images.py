# StudentAssessment/AssessmentImage moved here from the now-removed student_assessments/assessment_images apps.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('assessments', '0001_initial'),
        ('students', '0003_alter_student_table_alter_studentguardian_table'),
        ('score_settings', '0002_merge_numeric_level_scores'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentAssessment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('caption', models.TextField(blank=True)),
                ('numeric_score', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('assessment', models.ForeignKey(db_column='assessment_id', on_delete=django.db.models.deletion.CASCADE, related_name='student_assessments', to='assessments.assessment')),
                ('level_score', models.ForeignKey(blank=True, db_column='level_score_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_assessments', to='score_settings.levelscore')),
                ('student', models.ForeignKey(db_column='student_id', on_delete=django.db.models.deletion.CASCADE, related_name='student_assessments', to='students.student')),
            ],
            options={
                'db_table': 'student_assessments',
            },
        ),
        migrations.AddConstraint(
            model_name='studentassessment',
            constraint=models.UniqueConstraint(fields=('assessment', 'student'), name='unique_student_assessment'),
        ),
        migrations.CreateModel(
            name='AssessmentImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image_data', models.ImageField(upload_to='assessments/images/')),
                ('caption', models.TextField(blank=True)),
                ('student_assessment', models.ForeignKey(db_column='student_assessment_id', on_delete=django.db.models.deletion.CASCADE, related_name='assessment_images', to='assessments.studentassessment')),
            ],
            options={
                'db_table': 'assessment_images',
            },
        ),
    ]
