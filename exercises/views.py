from datetime import datetime
from io import BytesIO
import json
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.mail import EmailMessage
from django.http import FileResponse, JsonResponse
from django.shortcuts import redirect, render

from .forms import UserRegisterForm, DoctorRegisterForm, QuestionForm, DoctorAdviceForm
from .models import Profile, ExerciseSession, Question, PatientAnswer, DoctorAdvice, Appointment

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# =============================================================================
# FUNCIONES DE UTILIDAD Y SEGURIDAD
# Estas funciones ayudan a verificar roles y preparar datos comunes.
# =============================================================================

def _is_doctor(user) -> bool:
    """
    Verifica si el usuario autenticado tiene rol de doctor o es staff (admin).
    Retorna True si es doctor, False en caso contrario.
    """
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    try:
        return user.profile.role == 'doctor'
    except Profile.DoesNotExist:
        return False


def _is_patient(user) -> bool:
    """
    Verifica si el usuario es un paciente (autenticado y no es doctor).
    """
    return user.is_authenticated and not _is_doctor(user)


def _get_available_doctors():
    """
    Busca y retorna una lista formateada de todos los doctores registrados.
    Se usa para los selectores de citas y reportes.
    """
    doctors = Profile.objects.filter(role='doctor').select_related('user')
    return [{
        'id': d.user.id,
        'name': d.user.get_full_name() or d.user.username,
        'email': d.user.email,
        'specialty': d.specialty or 'Rehabilitación Física'
    } for d in doctors]


def _quality_semaphore(score: float) -> str:
    """
    Clasifica el puntaje de calidad de la captura de video en tres niveles.
    Ayuda al doctor a saber si la medicion fue confiable.
    """
    if score >= 80:
        return 'Alta'
    if score >= 60:
        return 'Media'
    return 'Baja'


def _build_report_pdf(report_data: dict | None = None, observations: str = '') -> BytesIO:
    """
    Genera un archivo PDF profesional con el reporte clínico consolidado.
    Utiliza la libreria ReportLab para dibujar texto y datos en un canvas A4.
    """
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    report_data = report_data or {}

    margin_x = 48
    y = height - 60

    # Titulo principal del reporte
    pdf.setTitle('Reporte Axon-Pose')
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(margin_x, y, 'AXON-POSE - Reporte de Evaluación')

    y -= 24
    pdf.setFont('Helvetica', 10)
    pdf.drawString(margin_x, y, f'Fecha de emisión: {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    # --- SECCIÓN: DIAGNÓSTICO ACTUAL ---
    y -= 28
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin_x, y, 'Resumen de diagnóstico')

    y -= 20
    pdf.setFont('Helvetica', 11)
    latest_eval = report_data.get('latest_eval') or {}
    diagnostic_lines = [
        f"- Última prueba: {latest_eval.get('test_type', 'Sin datos registrados')}.",
        f"- Estabilidad actual: {latest_eval.get('stability', 'N/A')}%.",
        f"- Desviación actual: {latest_eval.get('deviation_cm', 'N/A')} cm.",
        f"- Alineación: {latest_eval.get('alignment', 'Sin determinar')}.",
        f"- Calidad de medición: {latest_eval.get('quality_score', 'N/A')}%.",
        f"- Semáforo de calidad: {_quality_semaphore(float(latest_eval.get('quality_score', 0) or 0))}.",
    ]
    for line in diagnostic_lines:
        pdf.drawString(margin_x, y, line)
        y -= 17

    # --- SECCIÓN: HISTORIAL ---
    y -= 10
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin_x, y, 'Historial reciente')

    y -= 20
    pdf.setFont('Helvetica', 11)
    eval_history = report_data.get('history', [])
    if eval_history:
        history_lines = [
            f"- {item['timestamp']} | {item['test_type']} | Estabilidad {item['stability']}% | Desviación {item['deviation_cm']} cm"
            for item in eval_history[-3:]
        ]
    else:
        history_lines = ['- Aún no se registraron sesiones en este dispositivo.']
    for line in history_lines:
        pdf.drawString(margin_x, y, line)
        y -= 17

    # --- SECCIÓN: OBSERVACIONES MÉDICAS ---
    y -= 10
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin_x, y, 'Observaciones')

    y -= 20
    pdf.setFont('Helvetica', 11)
    text_obj = pdf.beginText(margin_x, y)
    observations_text = observations.strip() or (
        'Paciente con progreso favorable en equilibrio dinámico. '
        'Mantener rutina terapéutica y seguimiento semanal.'
    )

    # Lógica de ajuste de texto automático para no salirse del PDF
    max_chars = 95
    for paragraph in observations_text.split('\n'):
        while len(paragraph) > max_chars:
            text_obj.textLine(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        text_obj.textLine(paragraph)
    pdf.drawText(text_obj)

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer


# =============================================================================
# VISTAS DE GESTIÓN DE USUARIOS (REGISTRO Y LOGIN)
# =============================================================================

@login_required
def registrar_paciente(request):
    """
    Permite al doctor registrar nuevos pacientes.
    Crea tanto el usuario de Django como el perfil extendido de Axon-Pose.
    """
    if not _is_doctor(request.user):
        messages.error(request, 'Solo los doctores pueden acceder a esta sección.')
        return redirect('inicio')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            # Crear usuario base
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.email = form.cleaned_data['email']
            user.save()
            # Crear perfil clínico relacionado
            Profile.objects.create(
                user=user,
                role='patient',
                ci=form.cleaned_data.get('ci', ''),
                phone=form.cleaned_data.get('phone', ''),
                age=form.cleaned_data.get('age'),
                patient_data=form.cleaned_data.get('patient_data', ''),
                emergency_contact_name=form.cleaned_data.get('emergency_contact_name', ''),
                emergency_contact_relationship=form.cleaned_data.get('emergency_contact_relationship', ''),
                emergency_contact_phone=form.cleaned_data.get('emergency_contact_phone', ''),
                emergency_contact_address=form.cleaned_data.get('emergency_contact_address', ''),
                emergency_contact_email=form.cleaned_data.get('emergency_contact_email', ''),
            )
            messages.success(request, 'Paciente registrado correctamente.')
            return redirect('registrar_paciente')
    else:
        form = UserRegisterForm()

    # Obtener lista de pacientes para mostrarla debajo del formulario
    pacientes = Profile.objects.filter(role='patient').select_related('user').order_by('-user__date_joined')
    
    context = {
        'form': form,
        'pacientes': pacientes
    }
    return render(request, 'exercises/registrar_paciente.html', context)


@login_required
def registrar_doctor(request):
    """
    Solo accesible para administradores (is_staff). Permite crear nuevas cuentas de doctor.
    """
    if not request.user.is_staff:
        messages.error(request, 'Solo los administradores pueden registrar doctores.')
        return redirect('inicio')

    if request.method == 'POST':
        form = DoctorRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            
            Profile.objects.create(
                user=user,
                role='doctor',
                phone=form.cleaned_data.get('phone', ''),
                specialty=form.cleaned_data.get('specialty', 'Medicina General')
            )
            messages.success(request, f'Doctor {user.username} registrado correctamente.')
            return redirect('registrar_doctor')
    else:
        form = DoctorRegisterForm()

    doctores = Profile.objects.filter(role='doctor').select_related('user')
    return render(request, 'exercises/registrar_doctor.html', {'form': form, 'doctores': doctores})


def login_view(request):
    """
    Gestiona la entrada al sistema. Redirige al Dashboard si es doctor
    o a la pantalla de Inicio si es paciente.
    """
    if request.user.is_authenticated:
        return redirect('inicio')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Bienvenido {username}')
                if _is_doctor(user):
                    return redirect('doctor_dashboard')
                return redirect('inicio')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')
    else:
        form = AuthenticationForm()

    # Personalización de campos para la UI
    form.fields['username'].widget.attrs.update({'placeholder': 'Usuario', 'autocomplete': 'off'})
    form.fields['password'].widget.attrs.update({'placeholder': 'Contraseña', 'autocomplete': 'new-password'})
    
    return render(request, 'exercises/login.html', {'form': form})


@login_required
def logout_view(request):
    """Cierra la sesión y vuelve a la pantalla inicial."""
    logout(request)
    return redirect('inicio')


# =============================================================================
# VISTAS PRINCIPALES Y DASHBOARDS
# =============================================================================

@login_required
def inicio(request):
    """Pantalla inicial del paciente. Muestra consejos médicos actualizados."""
    if _is_doctor(request.user):
        return redirect('doctor_dashboard')

    advices = DoctorAdvice.objects.filter(is_active=True)[:5]
    return render(request, 'exercises/inicio.html', {'advices': advices})


@login_required
def doctor_dashboard(request):
    """
    Vista central para el doctor administrador.
    Muestra estadísticas rápidas, citas próximas y permite publicar consejos.
    """
    if not _is_doctor(request.user):
        messages.error(request, 'Acceso restringido a doctores.')
        return redirect('inicio')

    if request.method == 'POST':
        advice_form = DoctorAdviceForm(request.POST)
        if advice_form.is_valid():
            advice = advice_form.save(commit=False)
            advice.doctor = request.user
            advice.save()
            messages.success(request, 'Consejo global publicado correctamente.')
            return redirect('doctor_dashboard')
    else:
        advice_form = DoctorAdviceForm(initial={'is_active': True})

    # Cargar datos para las tarjetas del dashboard
    upcoming_appointments = Appointment.objects.filter(
        doctor=request.user, 
        is_completed=False
    ).select_related('patient').order_by('date')[:5]
    
    context = {
        'advice_form': advice_form,
        'latest_advices': DoctorAdvice.objects.select_related('doctor')[:10],
        'upcoming_appointments': upcoming_appointments,
        'patient_count': Profile.objects.filter(role='patient').count(),
        'questionnaire_completed': PatientAnswer.objects.values('patient').distinct().count(),
        'session_count': ExerciseSession.objects.count(),
    }
    return render(request, 'exercises/doctor_dashboard.html', context)


@login_required
def editar_consejo(request, advice_id):
    """Permite al doctor editar un consejo previamente publicado."""
    if not _is_doctor(request.user):
        return redirect('inicio')
    advice = DoctorAdvice.objects.get(id=advice_id)
    if request.method == 'POST':
        form = DoctorAdviceForm(request.POST, instance=advice)
        if form.is_valid():
            form.save()
            messages.success(request, 'Consejo actualizado.')
            return redirect('doctor_dashboard')
    else:
        form = DoctorAdviceForm(instance=advice)
    return render(request, 'exercises/editar_consejo.html', {'form': form, 'advice': advice})


@login_required
def eliminar_consejo(request, advice_id):
    """Elimina un consejo de la base de datos."""
    if not _is_doctor(request.user):
        return redirect('inicio')
    advice = DoctorAdvice.objects.get(id=advice_id)
    advice.delete()
    messages.success(request, 'Consejo eliminado.')
    return redirect('doctor_dashboard')


@login_required
def editar_paciente(request, patient_id):
    """Permite editar los datos de un paciente registrado."""
    if not _is_doctor(request.user):
        return redirect('inicio')
    user = User.objects.get(id=patient_id)
    profile = user.profile
    if request.method == 'POST':
        form = UserRegisterForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()
            # Actualizar perfil manualmente
            profile.ci = form.cleaned_data.get('ci')
            profile.phone = form.cleaned_data.get('phone')
            profile.age = form.cleaned_data.get('age')
            profile.patient_data = form.cleaned_data.get('patient_data')
            profile.emergency_contact_name = form.cleaned_data.get('emergency_contact_name')
            profile.emergency_contact_relationship = form.cleaned_data.get('emergency_contact_relationship')
            profile.emergency_contact_phone = form.cleaned_data.get('emergency_contact_phone')
            profile.emergency_contact_address = form.cleaned_data.get('emergency_contact_address')
            profile.emergency_contact_email = form.cleaned_data.get('emergency_contact_email')
            profile.save()
            messages.success(request, 'Datos del paciente actualizados.')
            return redirect('registrar_paciente')
    else:
        # Pre-poblar el formulario con datos del usuario y perfil
        initial_data = {
            'ci': profile.ci,
            'phone': profile.phone,
            'age': profile.age,
            'patient_data': profile.patient_data,
            'emergency_contact_name': profile.emergency_contact_name,
            'emergency_contact_relationship': profile.emergency_contact_relationship,
            'emergency_contact_phone': profile.emergency_contact_phone,
            'emergency_contact_address': profile.emergency_contact_address,
            'emergency_contact_email': profile.emergency_contact_email,
        }
        form = UserRegisterForm(instance=user, initial=initial_data)
        # El password no debe ser obligatorio al editar
        form.fields['password'].required = False
        form.fields['password_confirm'].required = False

    return render(request, 'exercises/registrar_paciente.html', {'form': form, 'editing': True, 'patient': user})


@login_required
def eliminar_paciente(request, patient_id):
    """Elimina un paciente y toda su informacion relacionada."""
    if not _is_doctor(request.user):
        return redirect('inicio')
    user = User.objects.get(id=patient_id)
    user.delete()
    messages.success(request, 'Paciente eliminado correctamente.')
    return redirect('registrar_paciente')


# =============================================================================
# VISTAS DE EJERCICIOS Y EVALUACIÓN
# =============================================================================

@login_required
def ejercicios(request):
    """Menu con las 3 pruebas de equilibrio disponibles."""
    return render(request, 'exercises/index.html')

@login_required
def ejercicio_estatico(request):
    """Información sobre la prueba de Equilibrio Estático."""
    return render(request, 'exercises/ejercicio_estatico.html')

@login_required
def ejercicio_monopodal(request):
    """Información sobre la prueba de Soporte Monopodal."""
    return render(request, 'exercises/ejercicio_monopodal.html')

@login_required
def ejercicio_tandem(request):
    """Información sobre la prueba de Marcha Tandem."""
    return render(request, 'exercises/ejercicio_tandem.html')

@login_required
def evaluacion(request):
    """
    La vista más importante: Abre la cámara e inicia el motor de visión artificial.
    Si el usuario es doctor, le permite seleccionar un paciente para la prueba.
    """
    exercise = request.GET.get('exercise', 'Marcha Tandem')
    allowed_exercises = {'Equilibrio Estatico', 'Soporte Monopodal', 'Marcha Tandem'}
    selected_exercise = exercise if exercise in allowed_exercises else 'Marcha Tandem'
    
    patient_data = []
    if _is_doctor(request.user):
        patients = Profile.objects.filter(role='patient').select_related('user')
        for p in patients:
            last_session = ExerciseSession.objects.filter(patient=p.user).order_by('-created_at').first()
            patient_data.append({
                'full_name': p.user.get_full_name() or p.user.username,
                'last_stability': last_session.stability if last_session else 'N/A',
                'last_deviation': last_session.deviation_cm if last_session else 'N/A',
                'last_test': last_session.test_type if last_session else 'Ninguna',
                'last_date': last_session.created_at.strftime('%d/%m/%y') if last_session else '-'
            })

    context = {
        'selected_exercise': selected_exercise,
        'patient_list': patient_data,
        'is_doctor': _is_doctor(request.user)
    }
    return render(request, 'exercises/diagnostico.html', context)


# =============================================================================
# VISTAS DE ENCUESTA DINÁMICA
# =============================================================================

@login_required
def encuesta(request):
    """
    Muestra y procesa la encuesta de salud del paciente.
    Las preguntas son dinámicas y se cargan desde la base de datos.
    """
    active_questions = Question.objects.filter(is_active=True)
    answers_query = PatientAnswer.objects.filter(patient=request.user)
    user_answers = {a.question_id: a.response for a in answers_query}
    
    # Lógica para no mostrar la encuesta si ya se llenó
    is_editing = request.GET.get('edit') == 'true'
    already_filled = answers_query.exists() and not is_editing
    
    if request.method == 'POST':
        for q in active_questions:
            answer_text = request.POST.get(f'question_{q.id}')
            if answer_text:
                PatientAnswer.objects.update_or_create(
                    patient=request.user,
                    question=q,
                    defaults={'response': answer_text}
                )
        messages.success(request, 'Cuestionario guardado con éxito.')
        return redirect('encuesta')

    return render(request, 'exercises/encuesta.html', {
        'questions': active_questions,
        'user_answers': user_answers,
        'already_filled': already_filled
    })


@login_required
def gestionar_preguntas(request):
    """Panel del doctor para crear o desactivar preguntas de la encuesta."""
    if not _is_doctor(request.user):
        return redirect('inicio')
    
    if request.method == 'POST':
        form = QuestionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Pregunta añadida correctamente.')
            return redirect('gestionar_preguntas')
    else:
        form = QuestionForm()
    
    questions = Question.objects.all().order_by('-created_at')
    return render(request, 'exercises/gestionar_preguntas.html', {'form': form, 'questions': questions})


@login_required
def cargar_preguntas_estandar(request):
    """Carga automáticamente las 15 preguntas clínicas originales de Axon-Pose."""
    if not _is_doctor(request.user):
        return redirect('inicio')
    
    standard_questions = [
        '¿Ha sufrido alguna caída en los últimos 12 meses?',
        '¿Siente miedo a caerse al caminar dentro de casa?',
        '¿Utiliza algún apoyo para caminar (bastón, andador)?',
        '¿Siente mareos o pérdida de equilibrio al levantarse de una silla?',
        '¿Realiza alguna actividad física de forma regular?',
        '¿Cuántos días a la semana camina por lo menos 15 minutos seguidos?',
        '¿Tiene problemas de visión que no estén corregidos por gafas?',
        '¿Toma 3 o más medicamentos diariamente?',
        '¿Siente debilidad o falta de fuerza en las piernas?',
        '¿Tiene dolor en las articulaciones (rodillas, caderas, tobillos) al moverse?',
        '¿Evita salir de casa por miedo a caerse?',
        '¿Alguna vez ha necesitado ayuda para levantarse del suelo después de una caída?',
        '¿Su casa tiene obstáculos como alfombras sueltas, cables o poca iluminación?',
        '¿Conoce qué tipos de ejercicios ayudan a mejorar el equilibrio?',
        '¿Le gustaría recibir un plan de ejercicios para mejorar su estabilidad?'
    ]
    
    count = 0
    for text in standard_questions:
        if not Question.objects.filter(text=text).exists():
            Question.objects.create(text=text)
            count += 1
    
    if count > 0:
        messages.success(request, f'Se cargaron {count} preguntas estándar.')
    else:
        messages.info(request, 'Las preguntas ya existen en el sistema.')
    return redirect('gestionar_preguntas')


# =============================================================================
# VISTAS DE PROGRESO Y SEGUIMIENTO
# =============================================================================

@login_required
def progreso(request, patient_id=None):
    """
    Genera estadísticas detalladas y gráficas para un paciente.
    Se usa tanto para el paciente mismo como para el doctor que lo supervisa.
    """
    target_user = request.user
    is_viewing_other = False
    
    if patient_id and _is_doctor(request.user):
        target_user = User.objects.get(id=patient_id)
        is_viewing_other = True

    eval_history = get_eval_history(target_user)
    numeric_stability, numeric_deviation = [], []
    session_rows = []
    previous_stability = None
    by_exercise = defaultdict(lambda: {'count': 0, 'stability_sum': 0.0, 'deviation_sum': 0.0})

    # Procesar datos históricos para la tabla y gráficas
    for index, item in enumerate(eval_history, start=1):
        stab = item.get('stability', 0.0)
        dev = item.get('deviation_cm', 0.0)
        qual = item.get('quality_score', 0.0)

        numeric_stability.append(stab)
        numeric_deviation.append(dev)

        ex_name = item.get('test_type', 'General')
        by_exercise[ex_name]['count'] += 1
        by_exercise[ex_name]['stability_sum'] += stab
        by_exercise[ex_name]['deviation_sum'] += dev

        delta = None if previous_stability is None else round(stab - previous_stability, 1)
        previous_stability = stab

        session_rows.append({
            'session_number': index,
            'timestamp': item.get('timestamp', 'S/F'),
            'test_type': ex_name,
            'stability': stab,
            'deviation_cm': dev,
            'quality_score': qual,
            'quality_semaphore': _quality_semaphore(qual),
            'delta_stability': delta,
        })

    # Preparar el contexto de la plantilla
    context = {
        'target_user': target_user,
        'is_viewing_other': is_viewing_other,
        'history_count': len(eval_history),
        'avg_stability': round(sum(numeric_stability)/len(numeric_stability), 1) if numeric_stability else 0,
        'avg_deviation': round(sum(numeric_deviation)/len(numeric_deviation), 1) if numeric_deviation else 0,
        'best_stability': max(numeric_stability, default=0),
        'session_rows': list(reversed(session_rows)),
        'survey_responses': PatientAnswer.objects.filter(patient=target_user).select_related('question'),
        'chart_data': {
            'labels': [f"S{row['session_number']}" for row in session_rows],
            'stability': numeric_stability,
            'deviation': numeric_deviation,
        }
    }
    return render(request, 'exercises/historial.html', context)


@login_required
def progreso_pacientes(request):
    """Listado general de pacientes para que el doctor vea quién está trabajando y quién no."""
    if not _is_doctor(request.user):
        return redirect('progreso')

    profiles = Profile.objects.filter(role='patient').select_related('user')
    summary = []

    for profile in profiles:
        sessions = ExerciseSession.objects.filter(patient=profile.user)
        last = sessions.order_by('-created_at').first()
        
        avg_stab = sum(s.stability for s in sessions) / sessions.count() if sessions.exists() else 0
        survey_filled = PatientAnswer.objects.filter(patient=profile.user).exists()

        summary.append({
            'user_id': profile.user.id,
            'full_name': profile.user.get_full_name() or profile.user.username,
            'ci': profile.ci or '-',
            'sessions_count': sessions.count(),
            'last_activity': last.created_at if last else None,
            'avg_stability': round(avg_stab, 1),
            'status': 'Activo' if sessions.exists() else 'Inactivo',
            'survey_status': 'Completo' if survey_filled else 'No completo'
        })

    return render(request, 'exercises/progreso_pacientes.html', {'patients_summary': summary})


# =============================================================================
# VISTAS DE REPORTES Y CITAS
# =============================================================================

@login_required
def descargar_reporte_pdf(request):
    """Genera y sirve el PDF para descarga."""
    target_user = request.user
    p_id = request.GET.get('patient_id')
    if p_id and _is_doctor(request.user):
        target_user = User.objects.get(id=p_id)

    eval_history = get_eval_history(target_user)
    report_data = {'latest_eval': eval_history[-1] if eval_history else {}, 'history': eval_history}
    pdf_buffer = _build_report_pdf(report_data, observations=request.GET.get('obs', ''))
    
    return FileResponse(pdf_buffer, as_attachment=True, filename=f'reporte_{target_user.username}.pdf')


@login_required
def enviar_reporte_doctor(request):
    """Envía el PDF del reporte por correo electrónico al doctor."""
    if request.method != 'POST': return redirect('mi_doctor')

    doctor_email = request.POST.get('doctor_email', '').strip().lower()
    doctor_match = User.objects.filter(email=doctor_email, profile__role='doctor').first()

    if not doctor_match:
        messages.error(request, 'Doctor no encontrado.')
        return redirect('mi_doctor')

    eval_history = get_eval_history(request.user)
    report_data = {'latest_eval': eval_history[-1] if eval_history else {}, 'history': eval_history}
    pdf_buffer = _build_report_pdf(report_data, observations=request.POST.get('observaciones', ''))
    
    email = EmailMessage(
        subject=f'Reporte Axon-Pose: {request.user.username}',
        body='Se adjunta el reporte clínico de Axon-Pose.',
        to=[doctor_email],
    )
    email.attach('reporte_clinico.pdf', pdf_buffer.getvalue(), 'application/pdf')
    email.send(fail_silently=True)
    messages.success(request, 'Reporte enviado.')
    return redirect('mi_doctor')


@login_required
def agendar_cita(request):
    """Controlador para la agenda de citas clínicas."""
    doctors = _get_available_doctors()
    if _is_doctor(request.user):
        appointments = Appointment.objects.filter(doctor=request.user).order_by('date')
    else:
        appointments = Appointment.objects.filter(patient=request.user).order_by('date')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cancel':
            Appointment.objects.filter(id=request.POST.get('cita_id')).delete()
            messages.success(request, 'Cita cancelada.')
        else:
            try:
                dt_cita = datetime.strptime(f"{request.POST.get('fecha')} {request.POST.get('hora')}", '%Y-%m-%d %H:%M')
                if 8 <= dt_cita.hour < 18:
                    Appointment.objects.create(
                        doctor=User.objects.get(id=request.POST.get('doctor_id')),
                        patient=request.user, date=dt_cita, reason=request.POST.get('motivo')
                    )
                    messages.success(request, 'Cita agendada.')
                else:
                    messages.error(request, 'Horario no permitido (08-18h).')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')
        return redirect('agendar_cita')

    return render(request, 'exercises/agendar_cita.html', {'doctors': doctors, 'appointments': appointments})


@login_required
def mi_doctor(request):
    """Vista informativa sobre el doctor asignado y descarga de reportes."""
    return render(request, 'exercises/mi_doctor.html', {'doctors': _get_available_doctors()})


# =============================================================================
# API ENDPOINTS (PARA JS)
# =============================================================================

@login_required
def registrar_metricas(request):
    """Recibe los datos del análisis MediaPipe por POST y los guarda."""
    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            ExerciseSession.objects.create(
                patient=request.user,
                test_type=payload.get('testType'),
                stability=payload.get('stability'),
                deviation_cm=payload.get('deviationCm'),
                alignment=payload.get('alignment'),
                quality_score=payload.get('qualityScore')
            )
            return JsonResponse({'ok': True})
        except Exception as e:
            return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    return JsonResponse({'ok': False}, status=405)

# --- Funciones de limpieza/edición auxiliar ---

def get_eval_history(user):
    """Retorna una lista limpia de sesiones del usuario para procesar."""
    return [{
        'timestamp': s.created_at.strftime('%Y-%m-%d %H:%M'),
        'test_type': s.test_type,
        'stability': float(s.stability),
        'deviation_cm': float(s.deviation_cm),
        'alignment': s.alignment,
        'quality_score': float(s.quality_score),
    } for s in ExerciseSession.objects.filter(patient=user).order_by('created_at')]


@login_required
def editar_pregunta(request, question_id):
    """Edición de preguntas del doctor."""
    q = Question.objects.get(id=question_id)
    if request.method == 'POST':
        form = QuestionForm(request.POST, instance=q)
        if form.is_valid():
            form.save()
            return redirect('gestionar_preguntas')
    return render(request, 'exercises/editar_pregunta.html', {'form': QuestionForm(instance=q), 'question': q})


@login_required
def eliminar_pregunta(request, question_id):
    """Borrado de preguntas."""
    Question.objects.filter(id=question_id).delete()
    return redirect('gestionar_preguntas')
