from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exercises', '0013_dailysession_evaluation_sessionexercisedetail_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='assigned_doctors',
            field=models.ManyToManyField(
                blank=True,
                limit_choices_to={'profile__role': 'doctor'},
                related_name='assigned_patient_profiles',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Doctores asignados',
            ),
        ),
    ]
