from datetime import datetime
from io import BytesIO
import json
import logging
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .forms import (
    AppointmentForm,
    UserRegisterForm,
    DoctorRegisterForm,
    QuestionForm,
    DoctorAdviceForm,
)
from .models import (
    Profile, Evaluation, DailySession, SessionExerciseDetail, ExerciseRepetition,
    RombergTest, Question, PatientAnswer, DoctorAdvice, Appointment,
)
from .vision import clasificador, romberg

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


def _build_report_pdf(
    report_data: dict | None = None,
    observations: str = '',
    patient=None,
) -> BytesIO:
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

    # --- SECCIÓN: DATOS DEL PACIENTE ---
    y -= 28
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin_x, y, 'Datos del paciente')

    y -= 20
    pdf.setFont('Helvetica', 10)
    patient_lines = []
    if patient is not None:
        try:
            profile = patient.profile
        except Profile.DoesNotExist:
            profile = None

        patient_lines = [
            f"Nombre completo: {patient.get_full_name() or patient.username}",
            f"Edad: {(profile.age if profile else None) or 'No registrada'}",
            f"Teléfono: {(profile.phone if profile else None) or 'No registrado'}",
            f"Correo: {patient.email or 'No registrado'}",
        ]
        if profile is not None:
            doctors = profile.assigned_doctors.all()
            doctor_names = ', '.join(
                doctor.get_full_name() or doctor.username
                for doctor in doctors
            )
            patient_lines.append(
                f"Doctor asignado: {doctor_names or 'No asignado'}"
            )
    else:
        patient_lines = ['No se encontraron datos del paciente.']

    for line in patient_lines:
        for line_part in (line[i:i + 95] for i in range(0, len(line), 95)):
            pdf.drawString(margin_x, y, line_part)
            y -= 15

    # --- SECCIÓN: EVALUACIÓN DE ROMBERG (referencia inicial y final) ---
    y -= 13
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin_x, y, 'Evaluación de Romberg (balanceo lateral)')
    y -= 20
    pdf.setFont('Helvetica', 11)
    resumen = report_data.get('romberg') or {}
    lineas = []
    for nombre, t in (('Inicial', resumen.get('inicial')), ('Final', resumen.get('final'))):
        if t:
            lineas.append(
                f"- {nombre} ({timezone.localtime(t.created_at).strftime('%Y-%m-%d')}): "
                f"{t.sway_open_cm} cm con ojos abiertos ({t.side_open}), "
                f"{t.sway_closed_cm} cm con ojos cerrados ({t.side_closed})."
            )
            if t.doctor_note:
                lineas.append(f"  Nota del doctor: {t.doctor_note}")
    if resumen.get('cambio_cerrados') is not None:
        lineas.append(f"- Cambio con ojos cerrados: {resumen['cambio_cerrados']:+} cm "
                      f"(negativo = menos balanceo).")
    if not lineas:
        lineas = ['- Aún no se registró la evaluación inicial.']
    for line in lineas:
        pdf.drawString(margin_x, y, line[:100])
        y -= 17

    # --- SECCIÓN: RUTINA DIARIA (resultados del modelo) ---
    rutinas = report_data.get('rutinas')
    if rutinas:
        y -= 10
        pdf.setFont('Helvetica-Bold', 12)
        pdf.drawString(margin_x, y, 'Rutina diaria (entrenamiento)')
        y -= 20
        pdf.setFont('Helvetica', 11)
        lineas = [
            f"- Sesiones realizadas: {rutinas['num_sesiones']} (completadas: {rutinas['completadas']}).",
            f"- Repeticiones: {rutinas['repeticiones']} | correctas: {rutinas['correctas']} "
            f"| incorrectas: {rutinas['incorrectas']} | {rutinas['pct']}% correctas.",
        ]
        for e in rutinas['por_ejercicio']:
            if e['total']:
                lineas.append(f"- {e['nombre']}: {e['ok']}/{e['total']} correctas ({e['pct']}%). "
                              f"Error más frecuente: {e['error']}.")
        for s in rutinas['sesiones'][:3]:
            lineas.append(f"- Día {s['dia']} ({s['fecha'].strftime('%Y-%m-%d')}): {s['ok']}/{s['total']} "
                          f"correctas ({s['pct']}%), {s['estado'].lower()}.")
        for line in lineas:
            pdf.drawString(margin_x, y, line[:100])
            y -= 17
        if y < 160:
            pdf.showPage()
            y = height - 60

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
            if hasattr(request.user, 'profile') and request.user.profile.role == 'doctor':
                user.profile.assigned_doctors.add(request.user)
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
    # Resumen rápido para el paciente: días hechos, repeticiones correctas y próxima cita.
    reps = ExerciseRepetition.objects.filter(detail__session__patient=request.user)
    total = reps.count()
    correctas = reps.filter(result='OK').count()
    resumen = {
        'dias': DailySession.objects.filter(patient=request.user, status='COMPLETADA').count(),
        'total_reps': total,
        'pct_correctas': round(100 * correctas / total) if total else None,
        'proxima_cita': Appointment.objects.filter(
            patient=request.user, is_completed=False, status='PENDIENTE', date__gte=timezone.now()
        ).order_by('date').first(),
        'romberg_inicial': _romberg_valido(request.user, 'INICIAL'),
    }
    return render(request, 'exercises/inicio.html', {'advices': advices, 'resumen': resumen})


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
        'session_count': RombergTest.objects.count(),
        'routine_count': DailySession.objects.filter(exercise_details__samples_count__gt=0).distinct().count(),
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
            if hasattr(request.user, 'profile') and request.user.profile.role == 'doctor':
                profile.assigned_doctors.add(request.user)
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
    Evaluación de Romberg (medición de referencia). El paciente hace la INICIAL antes de su primera
    rutina y, si quiere, la FINAL al terminar el programa. El doctor ve las mediciones de cada
    paciente y puede dejar una nota.
    """
    is_doctor = _is_doctor(request.user)
    if is_doctor:
        patient_rows = []
        for profile in Profile.objects.filter(role='patient').select_related('user'):
            resumen = resumen_romberg(profile.user)
            patient_rows.append({
                'user': profile.user,
                'full_name': profile.user.get_full_name() or profile.user.username,
                'romberg': resumen,
                'tests': [resumen['inicial'], resumen['final']],
            })
        return render(request, 'exercises/diagnostico.html', {'is_doctor': True, 'patient_rows': patient_rows})

    resumen = resumen_romberg(request.user)
    # Qué evaluación toca: la inicial si falta; la final solo si el paciente la pide (?phase=FINAL).
    if not resumen['inicial']:
        evaluation_type = 'INICIAL'
    elif request.GET.get('phase', '').upper() == 'FINAL' and not resumen['final']:
        evaluation_type = 'FINAL'
    else:
        evaluation_type = None  # nada pendiente: se muestran los resultados
    return render(request, 'exercises/diagnostico.html', {
        'is_doctor': False,
        'evaluation_type': evaluation_type,
        'romberg': resumen,
        'romberg_cards': [(n, t) for n, t in (('Inicial', resumen['inicial']), ('Final', resumen['final'])) if t],
    })


@login_required
def rutina_diaria(request):
    """Prepara la siguiente sesión diaria sin crear duplicados."""
    if _is_doctor(request.user):
        return redirect('evaluacion')
    if not _romberg_valido(request.user, 'INICIAL'):
        # La página de evaluación ya explica que primero va la evaluación inicial.
        return redirect('evaluacion')
    requested_day = request.GET.get('day')
    if requested_day:
        try:
            day_number = int(requested_day)
        except (TypeError, ValueError):
            return redirect('rutina_diaria')
    else:
        ultima = DailySession.objects.filter(patient=request.user).order_by('-day_number').first()
        if ultima and ultima.status != 'COMPLETADA' and not ExerciseRepetition.objects.filter(
                detail__session=ultima).exists():
            # La sesión anterior se abrió pero no tiene ejercicios (p. ej. se recargó la página): se reutiliza.
            day_number = ultima.day_number
        else:
            day_number = (ultima.day_number if ultima else 0) + 1
    if not 1 <= day_number <= 15:
        messages.error(request, 'El ciclo de rehabilitación admite días del 1 al 15.')
        return redirect('ejercicios')
    session, _ = DailySession.objects.get_or_create(
        patient=request.user,
        day_number=day_number,
        defaults={'status': 'INCOMPLETA'},
    )
    return render(request, 'exercises/rutina_diaria.html', {
        'daily_session': session,
        'day_number': day_number,
        'routine': True,
    })


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
    Progreso de un paciente: rutina diaria (resultados del modelo), evaluaciones de Romberg y encuesta.
    Lo ve el paciente (su propio progreso) y el doctor (cualquier paciente).
    """
    target_user = request.user
    is_viewing_other = False
    if patient_id and _is_doctor(request.user):
        target_user = get_object_or_404(User, id=patient_id)
        is_viewing_other = True

    rutinas = resumen_rutinas(target_user)
    context = {
        'target_user': target_user,
        'is_viewing_other': is_viewing_other,
        'rutinas': rutinas,
        'rutina_grafico': rutinas['grafico'],
        'romberg': resumen_romberg(target_user),
        'romberg_tests': RombergTest.objects.filter(patient=target_user),
        'survey_responses': PatientAnswer.objects.filter(patient=target_user).select_related('question'),
    }
    return render(request, 'exercises/historial.html', context)


@login_required
def progreso_pacientes(request):
    """Listado general de pacientes para que el doctor vea quién está trabajando y quién no."""
    if not _is_doctor(request.user):
        return redirect('progreso')

    summary = []
    for profile in Profile.objects.filter(role='patient').select_related('user'):
        rutinas = resumen_rutinas(profile.user)
        romberg_paciente = resumen_romberg(profile.user)
        ultimo = romberg_paciente['final'] or romberg_paciente['inicial']
        actividades = [f for f in (ultimo.created_at if ultimo else None, rutinas['ultima']) if f]
        summary.append({
            'user_id': profile.user.id,
            'full_name': profile.user.get_full_name() or profile.user.username,
            'ci': profile.ci or '-',
            'romberg': romberg_paciente,
            'routine_sessions': rutinas['num_sesiones'],
            'routine_completed': rutinas['completadas'],
            'routine_reps': rutinas['repeticiones'],
            'routine_correct': rutinas['correctas'],
            'routine_pct': rutinas['pct'],
            'last_activity': max(actividades) if actividades else None,
            'status': 'Activo' if actividades else 'Inactivo',
            'survey_status': 'Completo' if PatientAnswer.objects.filter(patient=profile.user).exists() else 'No completo',
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
        target_user = get_object_or_404(User, id=p_id)

    report_data = {
        'romberg': resumen_romberg(target_user),
        'rutinas': resumen_rutinas(target_user),
    }
    pdf_buffer = _build_report_pdf(
        report_data,
        observations=request.GET.get('obs', ''),
        patient=target_user,
    )
    
    return FileResponse(pdf_buffer, as_attachment=True, filename=f'reporte_{target_user.username}.pdf')


@login_required
def agendar_cita(request):
    """Sincroniza la agenda de citas entre el doctor y sus pacientes."""
    is_doctor = _is_doctor(request.user)
    if is_doctor:
        assigned_patients = Profile.objects.filter(
            role='patient',
        ).select_related('user').order_by('user__first_name', 'user__last_name')
        appointments = Appointment.objects.filter(
            doctor=request.user,
        ).select_related('patient', 'patient__profile').order_by('date')
    else:
        assigned_patients = Profile.objects.none()
        appointments = Appointment.objects.filter(
            patient=request.user,
        ).select_related('doctor', 'doctor__profile').order_by('date')

    appointment_form = None
    if is_doctor:
        appointment_form = AppointmentForm(
            patient_queryset=User.objects.filter(
                profile__role='patient',
            ).order_by('first_name', 'last_name', 'username'),
        )

    if request.method == 'POST':
        if not is_doctor:
            messages.error(request, 'Los pacientes no pueden agendar ni cancelar citas.')
            return redirect('agendar_cita')

        action = request.POST.get('action')
        if action == 'cancel':
            cancelled_count = Appointment.objects.filter(
                id=request.POST.get('cita_id'),
                doctor=request.user,
            ).update(status='CANCELADA')
            if cancelled_count:
                messages.success(request, 'Cita cancelada.')
            else:
                messages.error(request, 'La cita no existe o no te pertenece.')
            return redirect('agendar_cita')
        else:
            appointment_form = AppointmentForm(
                request.POST,
                patient_queryset=User.objects.filter(
                    profile__role='patient',
                ).order_by('first_name', 'last_name', 'username'),
            )
            if appointment_form.is_valid():
                fecha = appointment_form.cleaned_data['fecha']
                hora = appointment_form.cleaned_data['hora']
                dt_cita = timezone.make_aware(
                    datetime.combine(fecha, hora),
                    timezone.get_current_timezone(),
                )
                Appointment.objects.create(
                    doctor=request.user,
                    patient=appointment_form.cleaned_data['patient'],
                    date=dt_cita,
                    reason=appointment_form.cleaned_data['motivo'].strip(),
                    status='PENDIENTE',
                )
                messages.success(request, 'Cita agendada.')
                return redirect('agendar_cita')

    next_appointment = appointments.filter(
        date__gte=timezone.now(),
        status='PENDIENTE',
    ).first() if not is_doctor else None

    return render(request, 'exercises/agendar_cita.html', {
        'patients': assigned_patients,
        'appointments': appointments,
        'next_appointment': next_appointment,
        'is_doctor': is_doctor,
        'appointment_form': appointment_form,
        'today': timezone.localdate().isoformat(),
    })


# =============================================================================
# API ENDPOINTS (PARA JS)
# =============================================================================

@login_required
def registrar_romberg(request):
    """
    Guarda una evaluación de Romberg (medición de referencia): recibe los puntos de las dos fases
    (30 s con ojos abiertos y 30 s con ojos cerrados) y calcula el balanceo con vision/romberg.py.
    INICIAL: una válida por paciente, antes de la primera rutina. FINAL: opcional, después de la inicial.
    Si la cámara no vio bien al paciente, se guarda como no válida y se puede repetir.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        evaluation_type = payload.get('evaluationType', 'INICIAL')
        if evaluation_type not in dict(RombergTest.TYPE_CHOICES):
            raise ValueError('Tipo de evaluación no válido.')
        if _romberg_valido(request.user, evaluation_type):
            return JsonResponse({'ok': False, 'error': 'Esta evaluación ya está registrada.'}, status=409)
        if evaluation_type == 'FINAL' and not _romberg_valido(request.user, 'INICIAL'):
            raise ValueError('Primero debe hacerse la evaluación inicial.')
        width = float(payload.get('width') or 640)
        height = float(payload.get('height') or 480)
        fases = payload.get('phases') or {}
        abiertos_frames, cerrados_frames = fases.get('open') or [], fases.get('closed') or []
        if not isinstance(abiertos_frames, list) or not isinstance(cerrados_frames, list):
            raise ValueError('Faltan los puntos de las fases.')
        abiertos = romberg.analizar_fase(abiertos_frames, width, height)
        cerrados = romberg.analizar_fase(cerrados_frames, width, height)
        test = RombergTest.objects.create(
            patient=request.user,
            evaluation_type=evaluation_type,
            valid=romberg.es_valida(abiertos, cerrados),
            open_eyes=abiertos,
            closed_eyes=cerrados,
            sway_open_cm=abiertos['amplitud_cm'],
            sway_closed_cm=cerrados['amplitud_cm'],
            side_open=abiertos['lado'],
            side_closed=cerrados['lado'],
            romberg_ratio=romberg.cociente_romberg(abiertos, cerrados),
            reference_points={
                'puntos': list(romberg.PUNTOS_ROMBERG),
                'ancho': width,
                'alto': height,
                'open': romberg.puntos_referencia(abiertos_frames),
                'closed': romberg.puntos_referencia(cerrados_frames),
            },
        )
        return JsonResponse({
            'ok': True,
            'id': test.id,
            'valid': test.valid,
            'type': test.get_evaluation_type_display(),
            'open': abiertos,
            'closed': cerrados,
        })
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
        return JsonResponse({'ok': False, 'error': str(error)}, status=400)
    except Exception as error:  # responder siempre en JSON
        logging.getLogger(__name__).exception('Error en registrar_romberg')
        return JsonResponse({'ok': False, 'error': f'Error al guardar la evaluación: {error}'}, status=500)


@login_required
def nota_romberg(request, test_id):
    """El doctor deja una nota en una evaluación de Romberg (p. ej. si el paciente se sujetó)."""
    if not _is_doctor(request.user):
        messages.error(request, 'Solo el doctor puede anotar la evaluación.')
        return redirect('inicio')
    test = get_object_or_404(RombergTest, id=test_id)
    if request.method == 'POST':
        test.doctor_note = request.POST.get('note', '').strip()[:300]
        test.noted_by = request.user
        test.noted_at = timezone.now()
        test.save(update_fields=['doctor_note', 'noted_by', 'noted_at'])
        messages.success(request, 'Nota guardada.')
    siguiente = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        return redirect(siguiente)
    return redirect('evaluacion')


@login_required
def registrar_repeticion(request, session_id):
    """Registra atómicamente el resultado de una repetición de entrenamiento."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        exercise_name = payload.get('exerciseName')
        result = payload.get('result')
        duration = int(payload.get('durationSec', 30))
        stability = float(payload.get('stabilityPct', 0))
        deviation = float(payload.get('deviationCm', 0))
        if exercise_name not in dict(Evaluation.EXERCISE_CHOICES):
            raise ValueError('Ejercicio no válido.')
        if result not in {'OK', 'NOK'}:
            raise ValueError('El resultado debe ser OK o NOK.')
        if not 1 <= duration <= 30 or not 0 <= stability <= 100 or deviation < 0:
            raise ValueError('Las métricas de la repetición no son válidas.')

        with transaction.atomic():
            session = DailySession.objects.select_for_update().get(
                id=session_id,
                patient=request.user,
            )
            if session.status == 'COMPLETADA':
                return JsonResponse({'ok': False, 'error': 'La sesión ya está completada.'}, status=409)
            detail, _ = SessionExerciseDetail.objects.get_or_create(
                session=session,
                exercise_name=exercise_name,
            )
            side = payload.get('side', '')
            ExerciseRepetition.objects.create(
                detail=detail,
                result=result,
                duration_sec=duration,
                stability_pct=stability,
                deviation_cm=deviation,
                side=side if side in {'der', 'izq'} else '',
                model_windows=max(int(payload.get('modelWindows', 0) or 0), 0),
                model_incorrect_pct=min(max(float(payload.get('modelIncorrectPct', 0) or 0), 0), 100),
                main_error=str(payload.get('mainError', '') or '')[:40],
                latency_ms=max(float(payload.get('latencyMs', 0) or 0), 0),
                fps=max(float(payload.get('fps', 0) or 0), 0),
            )
            repetitions = detail.repetitions.all()
            count = repetitions.count()
            detail.correct_repetitions = repetitions.filter(result='OK').count()
            detail.incorrect_repetitions = repetitions.filter(result='NOK').count()
            detail.total_duration_sec = sum(item.duration_sec for item in repetitions)
            detail.average_stability_pct = sum(float(item.stability_pct) for item in repetitions) / count
            detail.average_deviation_cm = sum(float(item.deviation_cm) for item in repetitions) / count
            detail.samples_count = count
            detail.save()
        return JsonResponse({'ok': True, 'correct': detail.correct_repetitions, 'incorrect': detail.incorrect_repetitions})
    except DailySession.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada.'}, status=404)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        return JsonResponse({'ok': False, 'error': str(error)}, status=400)
    except Exception as error:  # p. ej. migración pendiente: responder en JSON, no en HTML
        logging.getLogger(__name__).exception('Error en registrar_repeticion')
        return JsonResponse({'ok': False, 'error': f'Error al guardar la repetición: {error}'}, status=500)


@login_required
def finalizar_rutina(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)
    with transaction.atomic():
        try:
            session = DailySession.objects.select_for_update().get(
                id=session_id, patient=request.user,
            )
        except DailySession.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Sesión no encontrada.'}, status=404)
        expected = set(Evaluation.ROUTINE_EXERCISES)
        completed = set(session.exercise_details.filter(samples_count__gt=0).values_list('exercise_name', flat=True))
        session.status = 'COMPLETADA' if expected <= completed else 'INCOMPLETA'
        session.save(update_fields=['status'])
    return JsonResponse({'ok': True, 'status': session.status})


@login_required
def analizar_pose(request):
    """
    Recibe ~1 s de fotogramas (33 puntos de MediaPipe cada uno) y devuelve si la postura es
    correcta o incorrecta, el error principal y el mensaje de corrección.
    Modelos (entrenados el 26-oct-2026): SVM en tándem; regresión logística en unipodal y árbol.
    No se guarda video: solo se procesan coordenadas.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        test_type = payload.get('testType')
        side = payload.get('side', 'der')
        width = float(payload.get('width') or 640)
        height = float(payload.get('height') or 480)
        frames = payload.get('frames')
        if not isinstance(frames, list) or not frames:
            raise ValueError('La cámara no envió fotogramas.')
        frames = frames[-90:]  # como máximo ~3 s

        if test_type in clasificador.EJERCICIOS:
            result = clasificador.clasificar(test_type, frames, width, height, side,
                                             bool(payload.get('inPosture')))
            incorrect = result.get('incorrecto', False)
            return JsonResponse({
                'ok': True,
                **result,
                # claves que ya usaba camera.js
                'alert': bool(result.get('valido') and incorrect),
                'message': result.get('mensaje', ''),
                'alignment': 'Requiere ajuste' if incorrect else 'Optima',
            })

        if test_type == 'Equilibrio Estatico':
            # Romberg: balanceo de los últimos segundos (frames en el formato de 7 puntos de romberg.py)
            fase = romberg.analizar_fase(frames, width, height)
            if fase['amplitud'] is None:
                return JsonResponse({'ok': True, 'valido': False,
                                     'message': 'Colóquese de cuerpo entero frente a la cámara'})
            lado = '' if fase['lado'] == 'centro' else f" hacia la {fase['lado']}"
            return JsonResponse({
                'ok': True,
                'valido': True,
                'amplitud_cm': fase['amplitud_cm'],
                'lado': fase['lado'],
                'tronco_g': fase['tronco_g'],
                'message': f"Balanceo {fase['amplitud_cm']} cm{lado}",
            })

        raise ValueError(f'Prueba no configurada: {test_type or "sin nombre"}.')
    except (json.JSONDecodeError, TypeError, ValueError, IndexError, KeyError) as error:
        return JsonResponse({'ok': False, 'error': str(error)}, status=400)
    except (ImportError, OSError) as error:
        return JsonResponse(
            {'ok': False, 'error': f'No se pudo cargar el modelo: {error}'},
            status=500,
        )
    except Exception as error:  # nunca devolver una página HTML de error a camera.js
        logging.getLogger(__name__).exception('Error en analizar_pose')
        return JsonResponse({'ok': False, 'error': f'Error interno del modelo: {error}'}, status=500)


# --- Romberg: evaluación inicial y final de referencia ---

def _romberg_valido(user, tipo):
    """La evaluación de Romberg válida más reciente del tipo dado ('INICIAL' o 'FINAL'), o None."""
    return RombergTest.objects.filter(patient=user, evaluation_type=tipo, valid=True).first()


def resumen_romberg(user):
    """Evaluación inicial y final (si existe) y cuánto cambió el balanceo (cm; negativo = menos balanceo)."""
    inicial, final = _romberg_valido(user, 'INICIAL'), _romberg_valido(user, 'FINAL')

    def cambio(campo):
        a = getattr(inicial, campo, None) if inicial else None
        b = getattr(final, campo, None) if final else None
        return None if a is None or b is None else round(float(b) - float(a), 1)

    return {
        'inicial': inicial,
        'final': final,
        'cambio_abiertos': cambio('sway_open_cm'),
        'cambio_cerrados': cambio('sway_closed_cm'),
    }


# --- Resumen de la rutina diaria (entrenamiento con el modelo) ---

EJERCICIO_NOMBRE = {
    'Marcha Tandem': 'Posición en tándem',
    'Soporte Monopodal': 'Apoyo unipodal',
    'Postura del Arbol': 'Postura del árbol',
}
ERROR_NOMBRE = {
    'tronco_inclinado': 'Tronco inclinado',
    'tronco_adelante': 'Tronco hacia adelante',
    'tronco_atras': 'Tronco hacia atrás',
    'cabeza_abajo': 'Cabeza abajo',
    'brazos_elevados': 'Brazos muy arriba',
    'brazos_abajo': 'Brazos abajo',
    'brazos_recogidos': 'Brazos recogidos',
    'pierna_cruzada': 'Pierna cruzada',
    'perdida_equilibrio': 'Pérdida de equilibrio',
    'pies_separados': 'Pies separados',
    'pie_bajo': 'Pie poco elevado',
    'pie_detras': 'Pie hacia atrás',
    'pie_en_suelo': 'Pie en el suelo',
    'pie_sobre_rodilla': 'Pie sobre la rodilla',
    'fuera_de_posicion': 'Fuera de la postura',
}


def _nombre_error(clave):
    return ERROR_NOMBRE.get(clave, (clave or '').replace('_', ' ').capitalize())


def _pct(ok, total):
    return round(100.0 * ok / total, 1) if total else 0.0


def resumen_rutinas(user):
    """
    Acumula los resultados de todas las rutinas diarias del paciente:
    sesiones, repeticiones correctas/incorrectas por ejercicio y por pierna, errores más frecuentes
    y el detalle de cada repetición (evidencia del modelo). Solo cuenta sesiones con repeticiones.
    """
    sesiones = (
        DailySession.objects.filter(patient=user)
        .prefetch_related('exercise_details__repetitions')
        .order_by('day_number')
    )
    orden = list(Evaluation.ROUTINE_EXERCISES)
    acum = {
        nombre: {'nombre': EJERCICIO_NOMBRE.get(nombre, nombre), 'total': 0, 'ok': 0,
                 'der_total': 0, 'der_ok': 0, 'izq_total': 0, 'izq_ok': 0, 'errores': defaultdict(int)}
        for nombre in orden
    }
    filas, ultima = [], None
    total = correctas = completadas = 0
    for sesion in sesiones:
        detalles = sorted(
            sesion.exercise_details.all(),
            key=lambda d: orden.index(d.exercise_name) if d.exercise_name in orden else 99,
        )
        ejercicios, repeticiones = [], []
        s_total = s_ok = 0
        for detalle in detalles:
            reps = sorted(detalle.repetitions.all(), key=lambda r: r.created_at)
            if not reps:
                continue
            a = acum.setdefault(detalle.exercise_name, {
                'nombre': EJERCICIO_NOMBRE.get(detalle.exercise_name, detalle.exercise_name), 'total': 0,
                'ok': 0, 'der_total': 0, 'der_ok': 0, 'izq_total': 0, 'izq_ok': 0, 'errores': defaultdict(int)})
            e_ok = sum(1 for r in reps if r.result == 'OK')
            errores = defaultdict(int)
            for r in reps:
                bien = r.result == 'OK'
                a['total'] += 1
                a['ok'] += bien
                if r.side in ('der', 'izq'):
                    a[r.side + '_total'] += 1
                    a[r.side + '_ok'] += bien
                if not bien and r.main_error:
                    errores[r.main_error] += 1
                    a['errores'][r.main_error] += 1
                ultima = r.created_at if ultima is None or r.created_at > ultima else ultima
                repeticiones.append({
                    'ejercicio': EJERCICIO_NOMBRE.get(detalle.exercise_name, detalle.exercise_name),
                    'pierna': {'der': 'Derecha', 'izq': 'Izquierda'}.get(r.side, '-'),
                    'resultado': r.result,
                    'pct_incorrecto': float(r.model_incorrect_pct),
                    'error': _nombre_error(r.main_error) if r.main_error else '-',
                    'duracion': r.duration_sec,
                    'hora': r.created_at,
                })
            principal = max(errores, key=errores.get) if errores else ''
            ejercicios.append({
                'nombre': EJERCICIO_NOMBRE.get(detalle.exercise_name, detalle.exercise_name),
                'ok': e_ok, 'total': len(reps), 'pct': _pct(e_ok, len(reps)),
                'error': _nombre_error(principal) if principal else '',
            })
            s_total += len(reps)
            s_ok += e_ok
        if not s_total:
            continue  # sesión abierta sin ejercicios realizados
        total += s_total
        correctas += s_ok
        completadas += sesion.status == 'COMPLETADA'
        filas.append({
            'id': sesion.id, 'dia': sesion.day_number, 'fecha': sesion.date, 'estado': sesion.status,
            'ok': s_ok, 'total': s_total, 'pct': _pct(s_ok, s_total),
            'ejercicios': ejercicios, 'repeticiones': repeticiones,
        })
    por_ejercicio = []
    for nombre in list(acum):
        a = acum[nombre]
        if not a['total'] and nombre not in orden:
            continue
        principal = max(a['errores'], key=a['errores'].get) if a['errores'] else ''
        por_ejercicio.append({
            'nombre': a['nombre'], 'total': a['total'], 'ok': a['ok'], 'nok': a['total'] - a['ok'],
            'pct': _pct(a['ok'], a['total']),
            'pct_der': _pct(a['der_ok'], a['der_total']) if a['der_total'] else None,
            'pct_izq': _pct(a['izq_ok'], a['izq_total']) if a['izq_total'] else None,
            'error': _nombre_error(principal) if principal else '-',
        })
    return {
        'sesiones': list(reversed(filas)),  # la más reciente primero
        'num_sesiones': len(filas),
        'completadas': completadas,
        'repeticiones': total,
        'correctas': correctas,
        'incorrectas': total - correctas,
        'pct': _pct(correctas, total),
        'por_ejercicio': por_ejercicio,
        'ultima': ultima,
        'grafico': {
            'labels': [f"Día {f['dia']}" for f in filas],
            'pct': [f['pct'] for f in filas],
            'por_ejercicio': [
                {'nombre': EJERCICIO_NOMBRE.get(n, n),
                 'datos': [next((e['pct'] for e in f['ejercicios'] if e['nombre'] == EJERCICIO_NOMBRE.get(n, n)), None)
                           for f in filas]}
                for n in orden
            ],
        },
    }


# --- Funciones de limpieza/edición auxiliar ---

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
