# Romberg como medición de referencia (26-oct-2026, bitácora D45): se quitan la sugerencia
# apto / no apto y la decisión del doctor; queda si la medición fue válida y una nota del doctor.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('exercises', '0017_rombergtest'),
    ]

    operations = [
        migrations.RemoveField(model_name='rombergtest', name='suggestion'),
        migrations.RemoveField(model_name='rombergtest', name='suggestion_reason'),
        migrations.RemoveField(model_name='rombergtest', name='threshold_cm'),
        migrations.RemoveField(model_name='rombergtest', name='decision'),
        migrations.RenameField(model_name='rombergtest', old_name='decided_by', new_name='noted_by'),
        migrations.RenameField(model_name='rombergtest', old_name='decided_at', new_name='noted_at'),
        migrations.AlterField(
            model_name='rombergtest',
            name='noted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='romberg_notes', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='rombergtest',
            name='valid',
            field=models.BooleanField(default=False, help_text='Las dos fases se midieron bien'),
        ),
    ]
