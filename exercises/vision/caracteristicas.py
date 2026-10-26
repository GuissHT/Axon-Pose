# -*- coding: utf-8 -*-
"""
caracteristicas.py - Proyecto Axon-Pose (tesis MGHT)

Modulo UNICO de caracteristicas posturales. Lo usan:
  - construir_ventanas.py (entrenamiento, sobre los CSV de MediaPipe)
  - Django (exercises/vision/), sobre los puntos que envia la pagina web

Esta escrito en Python puro (solo la libreria math) para no depender de NumPy en el servidor.

Entrada de cada fotograma: lista de 33 puntos (x, y, z, visibilidad) de MediaPipe Pose, con x e y
normalizados (0 a 1), el ancho y alto de la imagen en pixeles y el lado ('der' o 'izq') de la pierna
que trabaja (adelante en tandem, elevada en unipodal y arbol).

Todas las distancias se dividen por el ancho de hombros o por la longitud de la pierna de apoyo, para
que no dependan de la distancia a la camara ni de la estatura. Los angulos se calculan en pixeles.
"""
import math

VERSION = "1.0"
VIS_MIN = 0.5

# Indices de MediaPipe Pose
NARIZ, OREJA_I, OREJA_D = 0, 7, 8
HOMBRO_I, HOMBRO_D, MUNECA_I, MUNECA_D = 11, 12, 15, 16
CADERA_I, CADERA_D, RODILLA_I, RODILLA_D, TOBILLO_I, TOBILLO_D = 23, 24, 25, 26, 27, 28

MEDIDAS = [
    "tronco_lateral_g",      # inclinacion lateral del tronco respecto a la vertical (grados)
    "hombros_incl_g",        # inclinacion de la linea de hombros (grados)
    "cadera_incl_g",         # inclinacion de la linea de caderas (grados)
    "tronco_vertical",       # altura hombros-caderas / ancho de hombros (baja al inclinarse adelante/atras)
    "cabeza_altura",         # altura de la nariz sobre los hombros / ancho de hombros (baja con cabeza abajo)
    "orejas_altura",         # altura de las orejas sobre los hombros / ancho de hombros
    "brazos_altura",         # altura media de las munecas sobre los hombros / ancho de hombros
    "brazos_asimetria",      # diferencia de altura entre munecas / ancho de hombros
    "pie_elevacion",         # (tobillo apoyo - tobillo trabajo) en vertical / longitud pierna de apoyo
    "pie_vs_rodilla",        # (rodilla apoyo - tobillo trabajo) en vertical / pierna (>0: tobillo sobre la rodilla)
    "tobillos_separacion",   # distancia horizontal entre tobillos / ancho de hombros
    "pie_lado",              # posicion lateral del tobillo de trabajo hacia su propio lado (<0: cruzado)
    "rodilla_lado",          # idem para la rodilla de trabajo (<0: cruzada)
    "rodilla_apoyo_g",       # angulo cadera-rodilla-tobillo de la pierna de apoyo (grados)
    "rodilla_trabajo_g",     # angulo cadera-rodilla-tobillo de la pierna de trabajo (grados)
    "tobillo_trabajo_vis",   # visibilidad del tobillo de trabajo (baja si queda oculto, p. ej. pie detras)
]


def _p(lm, i, w, h):
    return lm[i][0] * w, lm[i][1] * h


def _angulo(a, b, c):
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    if n == 0:
        return float("nan")
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n))
    return math.degrees(math.acos(cos))


def _incl(a, b):
    """Inclinacion de la recta a-b respecto a la horizontal (0 = nivelada)."""
    return math.degrees(math.atan2(abs(a[1] - b[1]), abs(a[0] - b[0]) + 1e-9))


def fotograma(lm, ancho, alto, lado):
    """Medidas de un fotograma. Devuelve None si no se ven hombros y caderas."""
    if lm is None or len(lm) < 33:
        return None
    for i in (HOMBRO_I, HOMBRO_D, CADERA_I, CADERA_D):
        if lm[i][3] < VIS_MIN:
            return None
    w, h = ancho, alto
    hi, hd = _p(lm, HOMBRO_I, w, h), _p(lm, HOMBRO_D, w, h)
    ci, cd = _p(lm, CADERA_I, w, h), _p(lm, CADERA_D, w, h)
    ri, rd = _p(lm, RODILLA_I, w, h), _p(lm, RODILLA_D, w, h)
    ti, td = _p(lm, TOBILLO_I, w, h), _p(lm, TOBILLO_D, w, h)
    mi, md = _p(lm, MUNECA_I, w, h), _p(lm, MUNECA_D, w, h)
    nariz = _p(lm, NARIZ, w, h)
    oi, od = _p(lm, OREJA_I, w, h), _p(lm, OREJA_D, w, h)

    sw = math.hypot(hi[0] - hd[0], hi[1] - hd[1])
    if sw < 1:
        return None
    mh = ((hi[0] + hd[0]) / 2, (hi[1] + hd[1]) / 2)
    mc = ((ci[0] + cd[0]) / 2, (ci[1] + cd[1]) / 2)

    if lado == "der":
        c_t, r_t, t_t, vis_t = cd, rd, td, lm[TOBILLO_D][3]
        c_a, r_a, t_a = ci, ri, ti
    else:
        c_t, r_t, t_t, vis_t = ci, ri, ti, lm[TOBILLO_I][3]
        c_a, r_a, t_a = cd, rd, td
    pierna = math.hypot(c_a[0] - t_a[0], c_a[1] - t_a[1]) or 1.0

    # signo hacia "afuera" del lado de trabajo, usando la posicion real de las caderas
    afuera = 1.0 if (c_t[0] - c_a[0]) >= 0 else -1.0

    return {
        "tronco_lateral_g": math.degrees(math.atan2(abs(mh[0] - mc[0]), abs(mc[1] - mh[1]) + 1e-9)),
        "hombros_incl_g": _incl(hi, hd),
        "cadera_incl_g": _incl(ci, cd),
        "tronco_vertical": (mc[1] - mh[1]) / sw,
        "cabeza_altura": (mh[1] - nariz[1]) / sw,
        "orejas_altura": (mh[1] - (oi[1] + od[1]) / 2) / sw,
        "brazos_altura": (mh[1] - (mi[1] + md[1]) / 2) / sw,
        "brazos_asimetria": abs(mi[1] - md[1]) / sw,
        "pie_elevacion": (t_a[1] - t_t[1]) / pierna,
        "pie_vs_rodilla": (r_a[1] - t_t[1]) / pierna,
        "tobillos_separacion": abs(ti[0] - td[0]) / sw,
        "pie_lado": (t_t[0] - t_a[0]) * afuera / sw,
        "rodilla_lado": (r_t[0] - r_a[0]) * afuera / sw,
        "rodilla_apoyo_g": _angulo(c_a, r_a, t_a),
        "rodilla_trabajo_g": _angulo(c_t, r_t, t_t),
        "tobillo_trabajo_vis": vis_t,
        "_centro_x": mc[0] / sw,
        "_centro_y": mc[1] / sw,
    }


def _media_desv(vals):
    vals = [v for v in vals if v == v]  # quita NaN
    if not vals:
        return float("nan"), float("nan")
    m = sum(vals) / len(vals)
    d = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
    return m, d


def ventana(medidas_fotogramas):
    """Caracteristicas de una ventana (lista de dicts de fotograma(), sin los None).
    Para cada medida: media y desviacion estandar. Ademas, oscilacion del centro de caderas."""
    f = [m for m in medidas_fotogramas if m]
    if not f:
        return None
    out = {}
    for k in MEDIDAS:
        m, d = _media_desv([x[k] for x in f])
        out[k + "_media"] = m
        out[k + "_desv"] = d
    _, dx = _media_desv([x["_centro_x"] for x in f])
    _, dy = _media_desv([x["_centro_y"] for x in f])
    out["oscilacion_centro"] = math.hypot(dx, dy)
    return out


def nombres_caracteristicas():
    n = []
    for k in MEDIDAS:
        n += [k + "_media", k + "_desv"]
    return n + ["oscilacion_centro"]


# Mensajes de correccion asociados a cada medida (para la alerta del sistema)
MENSAJES = {
    "tronco_inclinado": "Enderece el tronco",
    "tronco_adelante": "Mantenga el tronco erguido",
    "tronco_atras": "Lleve el cuerpo al centro, no hacia atras",
    "cabeza_abajo": "Mire al frente",
    "brazos_elevados": "Baje los brazos a la altura de los hombros",
    "pierna_cruzada": "No cruce las piernas",
    "pies_separados": "Coloque un pie delante del otro, en linea",
    "pie_bajo": "Eleve mas el pie",
    "pie_detras": "Eleve el pie al frente",
    "pie_sobre_rodilla": "Baje el pie a la pantorrilla",
    "pie_en_suelo": "Apoye el pie en el tobillo o la pantorrilla",
    "perdida_equilibrio": "Mantenga la posicion firme",
}
