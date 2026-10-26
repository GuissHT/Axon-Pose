# -*- coding: utf-8 -*-
"""
Pruebas del clasificador de postura integrado (26-oct-2026).

Ejecutar:  python manage.py test exercises.tests_modelo

Usa 6 ventanas reales de 1 s del dataset (vision/modelos/ejemplos_prueba.json): un video correcto y
uno incorrecto por ejercicio, validados por la fisioterapeuta. Ademas, 3 ventanas de una persona parada
normalmente (primer segundo de un video), que no deben aceptarse como ninguno de los ejercicios.
"""
import json
import os

from django.contrib.auth.models import User
from django.test import Client, TestCase

from .models import DailySession, ExerciseRepetition, Profile, RombergTest
from .vision import clasificador

EJEMPLOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vision', 'modelos', 'ejemplos_prueba.json')


def cargar_ejemplos():
    with open(EJEMPLOS, encoding='utf-8') as fh:
        return json.load(fh)


class ClasificadorTests(TestCase):
    def test_modelos_cargan(self):
        for clave in ('tandem', 'unipodal', 'arbol'):
            modelo = clasificador.cargar(clave)
            self.assertEqual(len(modelo['caracteristicas']), 33)

    def test_ejemplos_reales(self):
        for ej in cargar_ejemplos():
            res = clasificador.clasificar(ej['prueba'], ej['frames'], ej['ancho'], ej['alto'], ej['lado'])
            self.assertTrue(res['valido'], ej['video'])
            self.assertEqual(res['estado'], ej['esperado'], ej['video'])
            self.assertEqual(res['en_posicion'], ej['posicion_esperada'], ej['video'])
            # coincide con la fisioterapeuta (fuera de posicion tambien cuenta como incorrecto)
            self.assertEqual(res['incorrecto'], ej['etiqueta'] == 'incorrecto', ej['video'])
            self.assertEqual(res['error'], ej['error_esperado'], ej['video'])
            self.assertLess(res['ms'], 200)

    def test_respuesta_siempre_es_json_valido(self):
        # Puntos degenerados (pies y rodillas en el mismo lugar): antes podia salir NaN y romper el JSON.
        lm = [[0.5, 0.5, 0, 1] for _ in range(33)]
        lm[11], lm[12], lm[23], lm[24] = [0.45, 0.3, 0, 1], [0.55, 0.3, 0, 1], [0.47, 0.6, 0, 1], [0.53, 0.6, 0, 1]
        for prueba in ('Marcha Tandem', 'Soporte Monopodal', 'Postura del Arbol'):
            res = clasificador.clasificar(prueba, [lm] * 30, 640, 480, 'izq')
            json.dumps(res, allow_nan=False)  # falla si hay NaN o infinito

    def test_parado_no_cuenta_como_ejercicio(self):
        # Antes, estar parado derecho con los brazos rectos se aceptaba como tandem y empezaba el conteo.
        parados = [ej for ej in cargar_ejemplos() if ej['video'].startswith('parado_normal')]
        self.assertEqual(len(parados), 3)
        for ej in parados:
            res = clasificador.clasificar(ej['prueba'], ej['frames'], ej['ancho'], ej['alto'], ej['lado'])
            self.assertFalse(res['en_posicion'], ej['prueba'])
            self.assertEqual(res['error'], 'fuera_de_posicion')
            self.assertTrue(res['mensaje'])

    def test_histeresis_y_pies_no_visibles(self):
        # Tandem un poco "abierto" (separacion 0,18): no basta para entrar, pero si para seguir dentro.
        lm = [[0.5, 0.5, 0, 1] for _ in range(33)]
        lm[11], lm[12] = [0.4, 0.3, 0, 1], [0.6, 0.3, 0, 1]          # hombros: 0,2 * 640 = 128 px
        lm[23], lm[24] = [0.45, 0.55, 0, 1], [0.55, 0.55, 0, 1]
        lm[27], lm[28] = [0.5, 0.92, 0, 1], [0.536, 0.95, -0.3, 1]   # tobillos a 0,18 anchos de hombros
        frames = [lm] * 20
        entra, _, _ = clasificador.comprobar_posicion('tandem', frames, 640, 480, 'der', False)
        sigue, _, _ = clasificador.comprobar_posicion('tandem', frames, 640, 480, 'der', True)
        self.assertFalse(entra)
        self.assertTrue(sigue)
        # Si la camara no ve los pies, se pide alejarse (antes se calificaba igual).
        lm2 = [list(p) for p in lm]
        lm2[27][3] = lm2[28][3] = 0.1
        ok, msg, _ = clasificador.comprobar_posicion('tandem', [lm2] * 20, 640, 480, 'der')
        self.assertFalse(ok)
        self.assertIn('pies', msg)

    def test_brazos_fuera_de_lugar(self):
        # El modelo de unipodal casi no usa los brazos: antes, hacerlo con los brazos abajo salia "correcto".
        for ej in cargar_ejemplos():
            if ej['etiqueta'] != 'correcto' or ej['video'].startswith('parado'):
                continue
            abajo = []
            for lm in ej['frames']:
                lm = [list(p) for p in lm]
                for hombro, codo, muneca, cadera in ((11, 13, 15, 23), (12, 14, 16, 24)):
                    largo = lm[cadera][1] - lm[hombro][1]
                    lm[codo][0], lm[codo][1] = lm[hombro][0], lm[hombro][1] + 0.45 * largo
                    lm[muneca][0], lm[muneca][1] = lm[hombro][0], lm[hombro][1] + 0.9 * largo
                abajo.append(lm)
            res = clasificador.clasificar(ej['prueba'], abajo, ej['ancho'], ej['alto'], ej['lado'])
            self.assertTrue(res['incorrecto'], ej['video'])
            self.assertEqual(res['error'], 'brazos_abajo', ej['video'])
            self.assertIn('Levante los brazos', res['mensaje'])
            self.assertIn('silla', res['mensaje'])

    def test_apoyo_con_una_mano_es_correcto(self):
        # Adulto mayor apoyado en la silla con una mano y el otro brazo en posicion: no es error.
        for ej in cargar_ejemplos():
            if ej['etiqueta'] != 'correcto' or ej['video'].startswith('parado'):
                continue
            for hombro, codo, muneca, cadera in ((11, 13, 15, 23), (12, 14, 16, 24)):
                apoyado = []
                for lm in ej['frames']:
                    lm = [list(p) for p in lm]
                    afuera = 0.06 if lm[hombro][0] >= lm[23 if hombro == 12 else 24][0] else -0.06
                    largo = lm[cadera][1] - lm[hombro][1]
                    lm[codo][0], lm[codo][1] = lm[hombro][0] + afuera / 2, lm[hombro][1] + 0.45 * largo
                    lm[muneca][0], lm[muneca][1] = lm[hombro][0] + afuera, lm[hombro][1] + 0.85 * largo
                    apoyado.append(lm)
                res = clasificador.clasificar(ej['prueba'], apoyado, ej['ancho'], ej['alto'], ej['lado'])
                self.assertEqual(res['estado'], 'correcto', (ej['video'], hombro, res['mensaje']))
                self.assertTrue(res['apoyo_silla'])

    def test_sigmoide_no_desborda(self):
        modelo = clasificador.cargar('unipodal')
        self.assertEqual(clasificador._probabilidad(modelo, -800), 0.0)
        self.assertEqual(clasificador._probabilidad(modelo, 800), 1.0)

    def test_sin_cuerpo(self):
        res = clasificador.clasificar('Marcha Tandem', [], 640, 480)
        self.assertFalse(res['valido'])


class ApiAnalizarPoseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('paciente_prueba', password='clave-prueba-123')
        Profile.objects.create(user=self.user, role='patient')
        self.client = Client()
        self.client.login(username='paciente_prueba', password='clave-prueba-123')

    def test_api_devuelve_decision_y_mensaje(self):
        for ej in cargar_ejemplos():
            resp = self.client.post('/api/analizar-pose/', data=json.dumps({
                'testType': ej['prueba'], 'side': ej['lado'], 'width': ej['ancho'],
                'height': ej['alto'], 'frames': ej['frames'],
            }), content_type='application/json')
            self.assertEqual(resp.status_code, 200, resp.content)
            data = resp.json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['incorrecto'], ej['etiqueta'] == 'incorrecto', ej['video'])
            self.assertEqual(data['en_posicion'], ej['posicion_esperada'], ej['video'])
            self.assertEqual(data['alert'], ej['etiqueta'] == 'incorrecto')
            self.assertTrue(data['message'])

    def test_api_prueba_desconocida(self):
        resp = self.client.post('/api/analizar-pose/', data=json.dumps({
            'testType': 'Otra', 'frames': [[[0, 0, 0, 1]] * 33]}), content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_repeticion_guarda_resultado_del_modelo(self):
        session = DailySession.objects.create(patient=self.user, day_number=1)
        resp = self.client.post(f'/api/rutinas/{session.id}/repeticiones/', data=json.dumps({
            'exerciseName': 'Postura del Arbol', 'result': 'NOK', 'durationSec': 30,
            'stabilityPct': 40, 'deviationCm': 0, 'side': 'izq', 'modelWindows': 58,
            'modelIncorrectPct': 72.4, 'mainError': 'pie_sobre_rodilla', 'latencyMs': 35.2, 'fps': 24.8,
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        rep = ExerciseRepetition.objects.get()
        self.assertEqual(rep.side, 'izq')
        self.assertEqual(rep.main_error, 'pie_sobre_rodilla')
        self.assertEqual(rep.model_windows, 58)

    def test_rutina_completa_con_tres_ejercicios(self):
        session = DailySession.objects.create(patient=self.user, day_number=1)
        for nombre in ('Marcha Tandem', 'Soporte Monopodal', 'Postura del Arbol'):
            self.client.post(f'/api/rutinas/{session.id}/repeticiones/', data=json.dumps({
                'exerciseName': nombre, 'result': 'OK', 'durationSec': 30, 'stabilityPct': 90, 'deviationCm': 0,
            }), content_type='application/json')
        resp = self.client.post(f'/api/rutinas/{session.id}/finalizar/')
        self.assertEqual(resp.json()['status'], 'COMPLETADA')


class ProgresoRutinaTests(TestCase):
    """Los resultados de la rutina diaria se guardan y se acumulan en las pantallas de progreso."""

    def setUp(self):
        self.paciente = User.objects.create_user('paciente_progreso', password='clave-prueba-123')
        Profile.objects.create(user=self.paciente, role='patient')
        self.doctor = User.objects.create_user('doctor_progreso', password='clave-prueba-123', is_staff=True)
        Profile.objects.create(user=self.doctor, role='doctor')
        # La rutina exige la evaluación inicial de Romberg (bitácora D45)
        RombergTest.objects.create(patient=self.paciente, evaluation_type='INICIAL', valid=True,
                                   sway_open_cm=2.0, sway_closed_cm=3.0)
        self.client = Client()
        self.client.login(username='paciente_progreso', password='clave-prueba-123')

    def _repeticion(self, session, nombre, resultado, lado, error=''):
        resp = self.client.post(f'/api/rutinas/{session.id}/repeticiones/', data=json.dumps({
            'exerciseName': nombre, 'result': resultado, 'durationSec': 20, 'stabilityPct': 80,
            'deviationCm': 0, 'side': lado, 'modelWindows': 38,
            'modelIncorrectPct': 80 if resultado == 'NOK' else 5, 'mainError': error,
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_recargar_la_rutina_no_gasta_un_dia(self):
        self.client.get('/rutina-diaria/')
        self.client.get('/rutina-diaria/')
        self.assertEqual(DailySession.objects.filter(patient=self.paciente).count(), 1)

    def test_resultados_se_acumulan_en_el_progreso(self):
        session = DailySession.objects.create(patient=self.paciente, day_number=1)
        self._repeticion(session, 'Marcha Tandem', 'OK', 'der')
        self._repeticion(session, 'Soporte Monopodal', 'NOK', 'izq', 'brazos_abajo')
        session2 = DailySession.objects.create(patient=self.paciente, day_number=2)
        self._repeticion(session2, 'Postura del Arbol', 'OK', 'der')

        # El paciente ve su progreso con la rutina acumulada
        resp = self.client.get('/mi-progreso/')
        self.assertEqual(resp.status_code, 200)
        rutinas = resp.context['rutinas']
        self.assertEqual(rutinas['num_sesiones'], 2)
        self.assertEqual(rutinas['repeticiones'], 3)
        self.assertEqual(rutinas['correctas'], 2)
        self.assertContains(resp, 'Brazos abajo')
        self.assertContains(resp, 'routineChart')

        # El PDF incluye la rutina
        pdf = self.client.get('/reportes/descargar-pdf/')
        self.assertEqual(pdf.status_code, 200)

        # El doctor la ve en el seguimiento, en el detalle del paciente y en su panel
        self.client.logout()
        self.client.login(username='doctor_progreso', password='clave-prueba-123')
        lista = self.client.get('/doctor/progreso-pacientes/')
        self.assertEqual(lista.status_code, 200)
        fila = [p for p in lista.context['patients_summary'] if p['user_id'] == self.paciente.id][0]
        self.assertEqual(fila['routine_reps'], 3)
        self.assertEqual(fila['routine_correct'], 2)
        self.assertEqual(fila['status'], 'Activo')
        detalle = self.client.get(f'/mi-progreso/{self.paciente.id}/')
        self.assertEqual(detalle.status_code, 200)
        self.assertEqual(detalle.context['rutinas']['repeticiones'], 3)
        panel = self.client.get('/doctor/dashboard/')
        self.assertEqual(panel.status_code, 200)
        self.assertEqual(panel.context['routine_count'], 2)
