# Integración del clasificador de postura (26-oct-2026):
# - agrega 'Postura del Arbol' a las opciones de ejercicio
# - guarda en cada repetición el resultado del modelo (sin video)
from django.db import migrations, models

EXERCISE_CHOICES = [
    ('Equilibrio Estatico', 'Equilibrio Estático'),
    ('Soporte Monopodal', 'Soporte Monopodal'),
    ('Marcha Tandem', 'Marcha Tándem'),
    ('Postura del Arbol', 'Postura del Árbol'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('exercises', '0015_appointment_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='evaluation',
            name='exercise_name',
            field=models.CharField(choices=EXERCISE_CHOICES, max_length=40),
        ),
        migrations.AlterField(
            model_name='sessionexercisedetail',
            name='exercise_name',
            field=models.CharField(choices=EXERCISE_CHOICES, max_length=40),
        ),
        migrations.AddField(
            model_name='exerciserepetition',
            name='side',
            field=models.CharField(blank=True, default='', help_text='Pierna que trabaja: der / izq', max_length=3),
        ),
        migrations.AddField(
            model_name='exerciserepetition',
            name='model_windows',
            field=models.PositiveIntegerField(default=0, help_text='Ventanas de 1 s analizadas'),
        ),
        migrations.AddField(
            model_name='exerciserepetition',
            name='model_incorrect_pct',
            field=models.DecimalField(decimal_places=2, default=0, help_text='% de ventanas clasificadas como incorrectas', max_digits=5),
        ),
        migrations.AddField(
            model_name='exerciserepetition',
            name='main_error',
            field=models.CharField(blank=True, default='', help_text='Error más frecuente', max_length=40),
        ),
        migrations.AddField(
            model_name='exerciserepetition',
            name='latency_ms',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Latencia media de la respuesta del modelo (ms)', max_digits=8),
        ),
        migrations.AddField(
            model_name='exerciserepetition',
            name='fps',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Fotogramas por segundo', max_digits=6),
        ),
    ]
