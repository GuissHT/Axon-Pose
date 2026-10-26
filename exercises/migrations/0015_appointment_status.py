from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exercises', '0014_profile_assigned_doctors'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente'),
                    ('COMPLETADA', 'Completada'),
                    ('CANCELADA', 'Cancelada'),
                ],
                default='PENDIENTE',
                max_length=12,
                verbose_name='Estado',
            ),
        ),
    ]
