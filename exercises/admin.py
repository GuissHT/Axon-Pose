from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Profile, ExerciseSession, Question, PatientAnswer, DoctorAdvice, Appointment

# =============================================================================
# CONFIGURACIÓN DEL PANEL DE ADMINISTRACIÓN (DJANGO ADMIN)
# Permite gestionar todos los datos del sistema desde /admin/
# =============================================================================

# --- Personalización de Usuarios y Perfiles ---

class ProfileInline(admin.StackedInline):
    """Permite editar el Perfil de Axon-Pose directamente dentro de la página del Usuario."""
    model = Profile
    can_delete = False
    verbose_name_plural = 'Perfil Detallado (Axon-Pose)'

class UserAdmin(BaseUserAdmin):
    """Extiende el administrador de usuarios de Django para mostrar el Rol."""
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'get_role')
    
    def get_role(self, obj):
        """Muestra si es Doctor o Paciente en la lista principal."""
        return obj.profile.get_role_display() if hasattr(obj, 'profile') else 'Sin Perfil'
    get_role.short_description = 'Rol del Usuario'

# Reemplazamos el administrador por defecto de Django por el nuestro personalizado
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# --- Registro de Modelos de Negocio ---

@admin.register(ExerciseSession)
class SessionAdmin(admin.ModelAdmin):
    """Administración de las sesiones capturadas con la cámara."""
    list_display = ('patient', 'test_type', 'stability', 'created_at')
    list_filter = ('test_type', 'created_at')
    search_fields = ('patient__username', 'test_type')

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    """Gestión de la agenda de citas clínicas."""
    list_display = ('patient', 'doctor', 'date', 'is_completed')
    list_filter = ('date', 'is_completed')
    ordering = ('-date',)

# Registros simples (sin personalización extra requerida)
admin.site.register(Question)      # Banco de preguntas
admin.site.register(PatientAnswer) # Respuestas de pacientes
admin.site.register(DoctorAdvice)   # Consejos publicados por doctores
