from django.db import models
from django.contrib.auth.models import User

# =============================================================================
# MODELO: Profile (Perfil de Usuario)
# Extiende la información de la cuenta de usuario de Django con datos médicos.
# =============================================================================
class Profile(models.Model):
    """
    Este modelo guarda la información adicional de cada persona en el sistema.
    Diferencia entre 'Doctor' (quien supervisa) y 'Paciente' (quien hace los ejercicios).
    """
    ROLE_CHOICES = (
        ('doctor', 'Doctor'),
        ('patient', 'Paciente'),
    )
    
    # Opciones de parentesco para el contacto de emergencia
    RELATIONSHIP_CHOICES = (
        ('Hijo/a', 'Hijo/a'),
        ('Hermano/a', 'Hermano/a'),
        ('Esposo/a', 'Esposo/a'),
        ('Padre/Madre', 'Padre o Madre'),
        ('Otro', 'Otro'),
    )

    # Vinculación con la cuenta principal de Django
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Datos básicos de identificación y rol
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='patient')
    ci = models.CharField(max_length=20, blank=True, null=True, verbose_name="Cédula de Identidad")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono/Celular")
    age = models.PositiveIntegerField(blank=True, null=True, verbose_name="Edad")
    
    # Datos exclusivos del Doctor
    specialty = models.CharField(max_length=100, blank=True, default='Medicina General', help_text="Especialidad médica")
    
    # Datos clínicos del Paciente
    patient_data = models.TextField(blank=True, default='', help_text="Antecedentes, enfermedades previas y alergias")
    
    # --- Contacto de Emergencia (Obligatorio para pacientes) ---
    emergency_contact_name = models.CharField(max_length=150, blank=True, default='', verbose_name="Nombre del Familiar")
    emergency_contact_relationship = models.CharField(max_length=100, choices=RELATIONSHIP_CHOICES, blank=True, default='', verbose_name="Parentesco")
    emergency_contact_phone = models.CharField(max_length=20, blank=True, default='', verbose_name="Celular del Familiar")
    emergency_contact_address = models.CharField(max_length=255, blank=True, default='', verbose_name="Dirección del Familiar")
    emergency_contact_email = models.EmailField(blank=True, default='', verbose_name="Correo del Familiar")

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


# =============================================================================
# MODELO: ExerciseSession (Sesión de Ejercicio)
# Registra cada vez que un paciente termina una prueba con la cámara.
# =============================================================================
class ExerciseSession(models.Model):
    """
    Guarda los resultados matemáticos obtenidos por el motor de visión artificial (MediaPipe).
    """
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exercise_sessions')
    test_type = models.CharField(max_length=100, default='Diagnóstico general', help_text="Ej: Marcha Tandem, Soporte Monopodal")
    
    # Métricas físicas
    stability = models.DecimalField(max_digits=5, decimal_places=2, default=0.0, help_text="Porcentaje de estabilidad (0 a 100)")
    deviation_cm = models.DecimalField(max_digits=5, decimal_places=2, default=0.0, help_text="Desviación lateral en centímetros")
    alignment = models.CharField(max_length=50, default='Sin determinar', help_text="Estado de alineación postural")
    
    # Calidad técnica de la prueba
    quality_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.0, help_text="Puntaje de calidad de video/captura")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y Hora")

    def __str__(self):
        return f"{self.test_type} - {self.patient.username} ({self.created_at.strftime('%d/%m/%y')})"


# =============================================================================
# MODELO: Question (Banco de Preguntas)
# Permite al doctor crear la encuesta de salud dinámicamente.
# =============================================================================
class Question(models.Model):
    """
    Define una pregunta que aparecerá en la encuesta del paciente.
    """
    text = models.CharField(max_length=255, verbose_name="Pregunta de Salud")
    is_active = models.BooleanField(default=True, verbose_name="¿Mostrar al paciente?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.text


# =============================================================================
# MODELO: PatientAnswer (Respuestas a la Encuesta)
# Registra las respuestas individuales de cada paciente.
# =============================================================================
class PatientAnswer(models.Model):
    """
    Asocia a un paciente con una pregunta y su respuesta (Sí o No).
    """
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='patient_answers')
    response = models.CharField(max_length=255, verbose_name="Elección") # Sí o No
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.patient.username} respondió '{self.response}' a: {self.question.text[:30]}..."


# =============================================================================
# MODELO: DoctorAdvice (Consejos Médicos)
# Recomendaciones generales publicadas por los doctores.
# =============================================================================
class DoctorAdvice(models.Model):
    """
    Aparecen en la página de inicio de todos los pacientes.
    """
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='published_advices')
    title = models.CharField(max_length=120, verbose_name="Título del Consejo")
    message = models.TextField(verbose_name="Recomendación Médica")
    is_active = models.BooleanField(default=True, verbose_name="Publicado")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Consejo: {self.title}"


# =============================================================================
# MODELO: Appointment (Agenda de Citas)
# Sistema de programación de consultas clínicas.
# =============================================================================
class Appointment(models.Model):
    """
    Guarda la fecha y el motivo por el cual un paciente verá a un doctor.
    """
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='doctor_appointments')
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='patient_appointments')
    date = models.DateTimeField(verbose_name="Fecha y Hora")
    reason = models.CharField(max_length=200, verbose_name="Motivo")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas del Doctor")
    is_completed = models.BooleanField(default=False, verbose_name="¿Cita concluida?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"Cita {self.patient.username} - {self.date.strftime('%d/%m/%y %H:%M')}"
