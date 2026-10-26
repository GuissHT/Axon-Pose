# -*- coding: utf-8 -*-
"""
Pruebas de la evaluación de Romberg con la cámara (vision/romberg.py; bitácora D39-D45).

Ejecutar:  python manage.py test exercises.tests_romberg

Se parte de una postura real del dataset (persona parada) y se simula un balanceo lateral de
amplitud conocida durante 30 s, para comprobar la medida, el guardado de la evaluación inicial y
final, que la rutina exija la inicial y la nota del doctor.
"""
import copy
import json
import math
import os

from django.contrib.auth.models import User
from django.test import Client, TestCase

from .models import Profile, RombergTest
from .vision import romberg

EJEMPLOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vision', 'modelos', 'ejemplos_prueba.json')


def postura_base():
    with open(EJEMPLOS, encoding='utf-8') as fh:
        ejemplo = [e for e in json.load(fh) if e['video'].startswith('parado')][0]
    return ejemplo['frames'][0], ejemplo['ancho'], ejemplo['alto']


def fase_simulada(amplitud, segundos=30, fps=20):
    """Fase de Romberg con un balanceo lateral de 'amplitud' anchos de hombros (pico a pico)."""
    base, ancho, alto = postura_base()
    hombros = math.hypot((base[11][0] - base[12][0]) * ancho, (base[11][1] - base[12][1]) * alto)
    fotogramas = []
    for k in range(segundos * fps):
        t = k * 1000 / fps
        desplazamiento = amplitud / 2 * math.sin(2 * math.pi * 0.4 * t / 1000) * hombros / ancho
        lm = copy.deepcopy(base)
        for i in (0, 11, 12, 23, 24):
            lm[i][0] += desplazamiento
        fotogramas.append({'t': t, 'p': romberg.de_33_puntos(lm)})
    return fotogramas, ancho, alto


class RombergCalculoTests(TestCase):
    def test_amplitud_crece_con_el_balanceo(self):
        quieto, ancho, alto = fase_simulada(0.05)
        mucho, _, _ = fase_simulada(0.40)
        a = romberg.analizar_fase(quieto, ancho, alto)
        b = romberg.analizar_fase(mucho, ancho, alto)
        self.assertTrue(romberg.es_valida(a, b))
        self.assertLess(a['amplitud'], b['amplitud'])
        self.assertIn(b['lado'], ('derecha', 'izquierda', 'centro'))

    def test_pocos_datos_no_es_valida(self):
        corta, ancho, alto = fase_simulada(0.05, segundos=5)
        normal, _, _ = fase_simulada(0.05)
        a = romberg.analizar_fase(corta, ancho, alto)
        b = romberg.analizar_fase(normal, ancho, alto)
        self.assertFalse(romberg.es_valida(a, b))
        self.assertIsNone(romberg.analizar_fase([], ancho, alto)['amplitud'])


class RombergApiTests(TestCase):
    def setUp(self):
        self.paciente = User.objects.create_user('paciente_romberg', password='clave-prueba-123')
        Profile.objects.create(user=self.paciente, role='patient')
        self.doctor = User.objects.create_user('doctor_romberg', password='clave-prueba-123', is_staff=True)
        Profile.objects.create(user=self.doctor, role='doctor')
        self.client = Client()
        self.client.login(username='paciente_romberg', password='clave-prueba-123')

    def _enviar(self, tipo, amp_abiertos=0.05, amp_cerrados=0.10, segundos=30):
        abiertos, ancho, alto = fase_simulada(amp_abiertos, segundos=segundos)
        cerrados, _, _ = fase_simulada(amp_cerrados, segundos=segundos)
        return self.client.post('/api/romberg/', data=json.dumps({
            'evaluationType': tipo, 'width': ancho, 'height': alto,
            'phases': {'open': abiertos, 'closed': cerrados},
        }), content_type='application/json')

    def test_balanceo_en_vivo(self):
        fase, ancho, alto = fase_simulada(0.10, segundos=3)
        resp = self.client.post('/api/analizar-pose/', data=json.dumps({
            'testType': 'Equilibrio Estatico', 'width': ancho, 'height': alto, 'frames': fase[-90:],
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['valido'])
        self.assertIn('Balanceo', resp.json()['message'])

    def test_rutina_exige_la_evaluacion_inicial(self):
        resp = self.client.get('/rutina-diaria/')
        self.assertRedirects(resp, '/evaluacion/', fetch_redirect_response=False)
        # Una evaluación mal medida (muy corta) no cuenta: se puede repetir
        self.assertFalse(self._enviar('INICIAL', segundos=5).json()['valid'])
        self.assertEqual(self.client.get('/rutina-diaria/').status_code, 302)
        resp = self._enviar('INICIAL')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['valid'])
        self.assertEqual(self.client.get('/rutina-diaria/').status_code, 200)
        # La inicial válida queda fija
        self.assertEqual(self._enviar('INICIAL').status_code, 409)

    def test_guarda_medidas_y_puntos(self):
        self._enviar('INICIAL', 0.05, 0.40)
        test = RombergTest.objects.get()
        self.assertTrue(test.valid)
        self.assertEqual(test.patient, self.paciente)
        self.assertEqual(len(test.reference_points['open']), 600)
        self.assertGreater(float(test.sway_closed_cm), float(test.sway_open_cm))

    def test_final_opcional_y_comparacion(self):
        self.assertEqual(self._enviar('FINAL').status_code, 400)  # primero la inicial
        self._enviar('INICIAL', 0.10, 0.30)
        self.assertEqual(self._enviar('FINAL', 0.05, 0.10).status_code, 200)
        resp = self.client.get('/mi-progreso/')
        cambio = resp.context['romberg']['cambio_cerrados']
        self.assertLess(cambio, 0)  # se balancea menos al final
        self.assertContains(resp, 'Evaluación de Romberg')

    def test_doctor_anota_y_ve_los_resultados(self):
        self._enviar('INICIAL')
        test = RombergTest.objects.get()
        # El paciente no puede anotar
        self.client.post(f'/doctor/romberg/{test.id}/nota/', {'note': 'x'})
        test.refresh_from_db()
        self.assertEqual(test.doctor_note, '')
        # El doctor sí
        self.client.logout()
        self.client.login(username='doctor_romberg', password='clave-prueba-123')
        resp = self.client.post(f'/doctor/romberg/{test.id}/nota/', {'note': 'Se sujetó de la silla'})
        self.assertEqual(resp.status_code, 302)
        test.refresh_from_db()
        self.assertEqual(test.doctor_note, 'Se sujetó de la silla')
        self.assertEqual(test.noted_by, self.doctor)
        self.assertContains(self.client.get('/evaluacion/'), 'Se sujetó de la silla')
        lista = self.client.get('/doctor/progreso-pacientes/')
        fila = [p for p in lista.context['patients_summary'] if p['user_id'] == self.paciente.id][0]
        self.assertEqual(fila['romberg']['inicial'], test)
        self.assertContains(self.client.get(f'/mi-progreso/{self.paciente.id}/'), 'Se sujetó de la silla')
        self.assertEqual(self.client.get(f'/reportes/descargar-pdf/?patient_id={self.paciente.id}').status_code, 200)

    def test_pagina_del_paciente(self):
        resp = self.client.get('/evaluacion/')
        self.assertEqual(resp.context['evaluation_type'], 'INICIAL')
        self.assertContains(resp, 'rombergResult')
        self._enviar('INICIAL')
        resp = self.client.get('/evaluacion/')
        self.assertIsNone(resp.context['evaluation_type'])  # nada pendiente: muestra resultados
        self.assertContains(resp, 'Ir a la rutina diaria')
        self.assertEqual(self.client.get('/evaluacion/?phase=FINAL').context['evaluation_type'], 'FINAL')
