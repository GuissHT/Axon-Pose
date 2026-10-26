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

    # Doctores responsables del seguimiento del paciente.
    assigned_doctors = models.ManyToManyField(
        User,
        blank=True,
        related_name='assigned_patient_profiles',
        limit_choices_to={'profile__role': 'doctor'},
        verbose_name='Doctores asignados',
    )
    
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
    Tabla antigua de resultados de la cámara. Ya no se llena: la evaluación de Romberg se guarda en
    RombergTest y la rutina en DailySession / ExerciseRepetition. Se conserva por los datos existentes.
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


class Evaluation(models.Model):
    """
    Evaluación basal o final por prueba (tabla antigua: ya no se crean registros; la evaluación de
    Romberg se guarda en RombergTest). Sus listas EXERCISE_CHOICES y ROUTINE_EXERCISES se usan en
    todo el sistema.
    """

    TYPE_CHOICES = (
        ('INICIAL', 'Inicial'),
        ('FINAL', 'Final'),
    )
    EXERCISE_CHOICES = (
        ('Equilibrio Estatico', 'Equilibrio Estático'),
        ('Soporte Monopodal', 'Soporte Monopodal'),
        ('Marcha Tandem', 'Marcha Tándem'),
        ('Postura del Arbol', 'Postura del Árbol'),
    )
    # Los tres ejercicios de la rutina diaria (tesis): tándem, apoyo unipodal y árbol.
    # 'Equilibrio Estatico' queda solo para la evaluación (Romberg).
    ROUTINE_EXERCISES = ('Marcha Tandem', 'Soporte Monopodal', 'Postura del Arbol')

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='evaluations')
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    exercise_name = models.CharField(max_length=40, choices=EXERCISE_CHOICES)
    date = models.DateTimeField(auto_now_add=True)
    stability_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    deviation_cm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    angle_deg = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['patient', 'type', 'exercise_name'],
                name='one_evaluation_per_phase_exercise',
            )
        ]
        ordering = ['date']


class RombergTest(models.Model):
    """
    Evaluación de Romberg medida con la cámara (vision/romberg.py; bitácora D39-D45).
    Es una MEDICIÓN DE REFERENCIA, no decide si el paciente es apto (el doctor ya lo evaluó):
    INICIAL, obligatoria antes de la primera rutina, y FINAL, opcional al terminar, para comparar.
    Dos fases de 30 s (ojos abiertos y ojos cerrados). Si la cámara no vio bien al paciente
    (valid = False), se puede repetir.
    """

    TYPE_CHOICES = (('INICIAL', 'Inicial'), ('FINAL', 'Final'))

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='romberg_tests')
    evaluation_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='INICIAL')
    created_at = models.DateTimeField(auto_now_add=True)
    valid = models.BooleanField(default=False, help_text="Las dos fases se midieron bien")
    # Medidas de cada fase (amplitud, lado, inclinación, velocidad, tronco, fotogramas útiles...)
    open_eyes = models.JSONField(default=dict, help_text="Medidas con ojos abiertos")
    closed_eyes = models.JSONField(default=dict, help_text="Medidas con ojos cerrados")
    sway_open_cm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    sway_closed_cm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    side_open = models.CharField(max_length=10, blank=True, default='')
    side_closed = models.CharField(max_length=10, blank=True, default='')
    romberg_ratio = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                        help_text="Balanceo con ojos cerrados / con ojos abiertos")
    # Puntos de referencia: por fotograma, tiempo (ms) y x, y de 7 puntos (nariz, hombros, caderas, tobillos)
    reference_points = models.JSONField(default=dict)
    # Nota del doctor
    doctor_note = models.CharField(max_length=300, blank=True, default='')
    noted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='romberg_notes')
    noted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


class DailySession(models.Model):
    """Sesión diaria de entrenamiento, con sus tres bloques de ejercicios."""

    STATUS_CHOICES = (
        ('COMPLETADA', 'Completada'),
        ('INCOMPLETA', 'Incompleta'),
    )

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_sessions')
    day_number = models.PositiveSmallIntegerField()
    date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='INCOMPLETA')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['patient', 'day_number'],
                name='one_daily_session_per_day_number',
            )
        ]
        ordering = ['day_number']


class SessionExerciseDetail(models.Model):
    """Acumulado de un ejercicio dentro de una sesión diaria."""

    EXERCISE_CHOICES = Evaluation.EXERCISE_CHOICES
    session = models.ForeignKey(DailySession, on_delete=models.CASCADE, related_name='exercise_details')
    exercise_name = models.CharField(max_length=40, choices=EXERCISE_CHOICES)
    correct_repetitions = models.PositiveIntegerField(default=0)
    incorrect_repetitions = models.PositiveIntegerField(default=0)
    total_duration_sec = models.PositiveIntegerField(default=0)
    average_stability_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    average_deviation_cm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    samples_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'exercise_name'],
                name='one_detail_per_session_exercise',
            )
        ]


class ExerciseRepetition(models.Model):
    """Evento inmutable emitido al terminar cada repetición (20 s en la rutina diaria: 6 por ejercicio)."""

    RESULT_CHOICES = (('OK', 'Correcta'), ('NOK', 'Incorrecta'))
    detail = models.ForeignKey(
        SessionExerciseDetail,
        on_delete=models.CASCADE,
        related_name='repetitions',
    )
    result = models.CharField(max_length=3, choices=RESULT_CHOICES)
    duration_sec = models.PositiveSmallIntegerField(default=30)
    stability_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    deviation_cm = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    # Resultado del clasificador de postura (modelo entrenado, 26-oct-2026)
    side = models.CharField(max_length=3, blank=True, default='', help_text="Pierna que trabaja: der / izq")
    model_windows = models.PositiveIntegerField(default=0, help_text="Ventanas de 1 s analizadas")
    model_incorrect_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                              help_text="% de ventanas clasificadas como incorrectas")
    main_error = models.CharField(max_length=40, blank=True, default='', help_text="Error más frecuente")
    latency_ms = models.DecimalField(max_digits=8, decimal_places=2, default=0,
                                     help_text="Latencia media de la respuesta del modelo (ms)")
    fps = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text="Fotogramas por segundo")
    created_at = models.DateTimeField(auto_now_add=True)


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
    STATUS_CHOICES = (
        ('PENDIENTE', 'Pendiente'),
        ('COMPLETADA', 'Completada'),
        ('CANCELADA', 'Cancelada'),
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='PENDIENTE',
        verbose_name='Estado',
    )
    is_completed = models.BooleanField(default=False, verbose_name="¿Cita concluida?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"Cita {self.patient.username} - {self.date.strftime('%d/%m/%y %H:%M')}"
