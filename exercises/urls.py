from django.urls import path
from . import views

# =============================================================================
# MAPEO DE RUTAS (URLS)
# Define qué dirección en el navegador activa cada función en views.py
# =============================================================================

urlpatterns = [
    # --- Rutas de Acceso (Públicas o de Inicio) ---
    path('', views.inicio, name='index'),                     # Raíz del sitio
    path('inicio/', views.inicio, name='inicio'),             # Página de inicio personalizada
    path('login/', views.login_view, name='login'),           # Formulario de entrada
    path('logout/', views.logout_view, name='logout'),         # Salida segura

    # --- Panel de Control del Doctor (Gestión Médica) ---
    path('doctor/dashboard/', views.doctor_dashboard, name='doctor_dashboard'),
    path('doctor/registrar-paciente/', views.registrar_paciente, name='registrar_paciente'),
    path('doctor/registrar-doctor/', views.registrar_doctor, name='registrar_doctor'),
    path('doctor/editar-paciente/<int:patient_id>/', views.editar_paciente, name='editar_paciente'),
    path('doctor/eliminar-paciente/<int:patient_id>/', views.eliminar_paciente, name='eliminar_paciente'),
    
    # --- Gestión Dinámica de Encuestas (Banco de Preguntas) ---
    path('doctor/gestionar-preguntas/', views.gestionar_preguntas, name='gestionar_preguntas'),
    path('doctor/editar-pregunta/<int:question_id>/', views.editar_pregunta, name='editar_pregunta'),
    path('doctor/eliminar-pregunta/<int:question_id>/', views.eliminar_pregunta, name='eliminar_pregunta'),
    path('doctor/cargar-preguntas-estandar/', views.cargar_preguntas_estandar, name='cargar_preguntas_estandar'),
    
    # --- Gestión de Consejos y Mensajes Globales ---
    path('doctor/editar-consejo/<int:advice_id>/', views.editar_consejo, name='editar_consejo'),
    path('doctor/eliminar-consejo/<int:advice_id>/', views.eliminar_consejo, name='eliminar_consejo'),

    # --- Rutas de Ejercicios y Motor de Visión (Pacientes) ---
    path('ejercicios/', views.ejercicios, name='ejercicios'),                  # Menú de ejercicios
    path('ejercicios/estatico/', views.ejercicio_estatico, name='ejercicio_estatico'),
    path('ejercicios/monopodal/', views.ejercicio_monopodal, name='ejercicio_monopodal'),
    path('ejercicios/tandem/', views.ejercicio_tandem, name='ejercicio_tandem'),
    path('evaluacion/', views.evaluacion, name='evaluacion'),                  # Pantalla de cámara

    # --- Seguimiento Clínico y Progreso ---
    path('encuesta-conocimiento/', views.encuesta, name='encuesta'),          # Formulario Sí/No
    path('mi-progreso/', views.progreso, name='progreso'),                    # Historial propio
    path('mi-progreso/<int:patient_id>/', views.progreso, name='progreso_paciente'), # Ver paciente (Doctor)
    path('doctor/progreso-pacientes/', views.progreso_pacientes, name='progreso_pacientes'), # Lista seguimiento

    # --- Contacto, Citas y Reportes PDF ---
    path('mi-doctor/', views.mi_doctor, name='mi_doctor'),                    # Página de contacto
    path('agendar-cita/', views.agendar_cita, name='agendar_cita'),           # Sistema de citas
    path('reportes/descargar-pdf/', views.descargar_reporte_pdf, name='descargar_reporte_pdf'),
    path('reportes/enviar-doctor/', views.enviar_reporte_doctor, name='enviar_reporte_doctor'),

    # --- API para recepción de datos en tiempo real (Desde camera.js) ---
    path('api/registrar-metricas/', views.registrar_metricas, name='registrar_metricas'),
]