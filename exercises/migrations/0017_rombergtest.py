# Evaluación de Romberg con la cámara (26-oct-2026, bitácora D39-D44):
# medidas por fase, sugerencia del sistema, decisión del doctor y puntos de referencia.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('exercises', '0016_postura_arbol_y_resultado_modelo'),
    ]

    operations = [
        migrations.CreateModel(
            name='RombergTest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('evaluation_type', models.CharField(choices=[('INICIAL', 'Inicial'), ('FINAL', 'Final')], default='INICIAL', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('open_eyes', models.JSONField(default=dict, help_text='Medidas con ojos abiertos')),
                ('closed_eyes', models.JSONField(default=dict, help_text='Medidas con ojos cerrados')),
                ('sway_open_cm', models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ('sway_closed_cm', models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ('side_open', models.CharField(blank=True, default='', max_length=10)),
                ('side_closed', models.CharField(blank=True, default='', max_length=10)),
                ('romberg_ratio', models.DecimalField(blank=True, decimal_places=2, help_text='Balanceo con ojos cerrados / con ojos abiertos', max_digits=6, null=True)),
                ('threshold_cm', models.DecimalField(decimal_places=1, default=0, help_text='Límite de balanceo usado para la sugerencia', max_digits=5)),
                ('suggestion', models.CharField(choices=[('APTO', 'Apto'), ('NO_APTO', 'No apto'), ('REPETIR', 'Repetir')], max_length=8)),
                ('suggestion_reason', models.CharField(blank=True, default='', max_length=200)),
                ('reference_points', models.JSONField(default=dict)),
                ('decision', models.CharField(blank=True, choices=[('', 'Pendiente'), ('APTO', 'Apto'), ('NO_APTO', 'No apto')], default='', max_length=8)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('doctor_note', models.CharField(blank=True, default='', max_length=300)),
                ('decided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='romberg_decisions', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='romberg_tests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
