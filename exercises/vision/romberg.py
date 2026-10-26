# -*- coding: utf-8 -*-
"""
romberg.py - Proyecto Axon-Pose (tesis MGHT)

Evaluacion de Romberg medida con la camara (no es un modelo entrenado). Bitacora D39-D45.

Es una MEDICION DE REFERENCIA, no decide si la persona es apta: el doctor ya la evaluo antes de
incluirla. Se hace una vez al inicio (obligatoria antes de la primera rutina) y, si se quiere, otra al
final del programa para comparar. La persona se para con los pies juntos 30 s con los ojos abiertos
y 30 s con los ojos cerrados, frente a la camara y con el doctor presente. De cada fotograma se usan 7 puntos de MediaPipe
(PUNTOS_ROMBERG) y se mide cuanto se balancea el tronco hacia los lados respecto de los pies:

    lateral = (centro del tronco - centro de los tobillos) / ancho de hombros
              centro del tronco = promedio del centro de hombros y del centro de caderas
              positivo = hacia la DERECHA del paciente (lado del hombro derecho, punto 12)

Medidas de cada fase:
    amplitud    rango del balanceo lateral (percentil 95 - percentil 5): no cuenta un fotograma suelto
    lado        hacia donde se aleja mas del centro de los pies (derecha, izquierda o centro)
    inclinacion posicion media del tronco respecto de los pies
    velocidad   recorrido lateral por segundo
    tronco_g    inclinacion lateral media del tronco (grados)

Una fase es valida si la camara vio a la persona en al menos el 70 % de los fotogramas y durante
al menos 15 s; si alguna fase no es valida, se pide repetir la evaluacion.
"""
import math

# Nariz, hombro izq., hombro der., cadera izq., cadera der., tobillo izq., tobillo der.
PUNTOS_ROMBERG = (0, 11, 12, 23, 24, 27, 28)
_NARIZ, _HI, _HD, _CI, _CD, _TI, _TD = range(7)

UMBRALES = {
    "lado_centro": 0.05,        # excursion menor a esto = "centro"
    "min_validos": 0.70,        # fraccion minima de fotogramas utiles
    "min_segundos": 15.0,       # tiempo minimo analizado por fase
}
ANCHO_HOMBROS_CM = 35.0  # solo para mostrar centimetros aproximados; las reglas usan anchos de hombros


def _percentil(vals, q):
    vals = sorted(vals)
    if not vals:
        return float("nan")
    pos = (len(vals) - 1) * q
    i = int(pos)
    j = min(i + 1, len(vals) - 1)
    return vals[i] + (vals[j] - vals[i]) * (pos - i)


def _lado(valor):
    if abs(valor) < UMBRALES["lado_centro"]:
        return "centro"
    return "derecha" if valor > 0 else "izquierda"


def de_33_puntos(lm):
    """Convierte un fotograma de 33 puntos [x, y, z, v] al formato de 7 puntos [x, y, v]."""
    return [[lm[i][0], lm[i][1], lm[i][3] if len(lm[i]) > 3 else 1.0] for i in PUNTOS_ROMBERG]


def analizar_fase(fotogramas, ancho, alto):
    """
    fotogramas: lista de {"t": milisegundos, "p": [[x, y, visibilidad] x 7]} (orden de PUNTOS_ROMBERG),
    con x, y normalizados 0-1 como los entrega MediaPipe. ancho, alto: tamano del video en pixeles.
    Devuelve un diccionario con las medidas de la fase (ver encabezado).
    """
    lateral, tiempos, tronco = [], [], []
    for f in fotogramas:
        p = f.get("p") if isinstance(f, dict) else None
        if not p or len(p) < 7:
            continue
        if min(p[_HI][2], p[_HD][2], p[_CI][2], p[_CD][2]) < 0.5 or min(p[_TI][2], p[_TD][2]) < 0.3:
            continue
        hx_i, hy_i, hx_d, hy_d = p[_HI][0] * ancho, p[_HI][1] * alto, p[_HD][0] * ancho, p[_HD][1] * alto
        sw = math.hypot(hx_d - hx_i, hy_d - hy_i)
        if sw < 1:
            continue
        derecha = 1.0 if hx_d >= hx_i else -1.0  # hacia donde queda el hombro derecho en la imagen
        hombros_x, hombros_y = (hx_i + hx_d) / 2, (hy_i + hy_d) / 2
        caderas_x = (p[_CI][0] + p[_CD][0]) / 2 * ancho
        caderas_y = (p[_CI][1] + p[_CD][1]) / 2 * alto
        tobillos_x = (p[_TI][0] + p[_TD][0]) / 2 * ancho
        centro_x = (hombros_x + caderas_x) / 2
        lateral.append((centro_x - tobillos_x) * derecha / sw)
        tronco.append(math.degrees(math.atan2((hombros_x - caderas_x) * derecha, caderas_y - hombros_y)))
        tiempos.append(float(f.get("t", 0)))

    total = len(fotogramas)
    utiles = len(lateral)
    segundos = (tiempos[-1] - tiempos[0]) / 1000.0 if utiles > 1 else 0.0
    resultado = {
        "fotogramas": total,
        "utiles": utiles,
        "pct_utiles": round(100.0 * utiles / total, 1) if total else 0.0,
        "segundos": round(segundos, 1),
    }
    if utiles < 2:
        resultado.update({"valida": False, "amplitud": None, "amplitud_cm": None, "lado": "",
                          "inclinacion": None, "velocidad": None, "tronco_g": None})
        return resultado

    p5, p95 = _percentil(lateral, 0.05), _percentil(lateral, 0.95)
    mediana = _percentil(lateral, 0.5)
    amplitud = p95 - p5
    # Lado: hacia donde se aleja mas del centro de los pies.
    lado = _lado(p95 if abs(p95) >= abs(p5) else p5)
    recorrido = sum(abs(b - a) for a, b in zip(lateral, lateral[1:]))
    resultado.update({
        "valida": resultado["pct_utiles"] >= 100 * UMBRALES["min_validos"]
                  and segundos >= UMBRALES["min_segundos"],
        "amplitud": round(amplitud, 3),
        "amplitud_cm": round(amplitud * ANCHO_HOMBROS_CM, 1),
        "lado": lado,
        "inclinacion": round(mediana, 3),
        "velocidad": round(recorrido / segundos, 3) if segundos > 0 else None,
        "tronco_g": round(_percentil(tronco, 0.5), 1),
    })
    return resultado


def es_valida(abiertos, cerrados):
    """True si las dos fases se midieron bien; si no, hay que repetir la evaluacion."""
    return bool(abiertos.get("valida") and cerrados.get("valida"))


def cociente_romberg(abiertos, cerrados):
    """Balanceo con ojos cerrados / con ojos abiertos (informativo)."""
    a, c = abiertos.get("amplitud"), cerrados.get("amplitud")
    if not a or c is None:
        return None
    return round(c / a, 2)


def puntos_referencia(fotogramas):
    """Puntos que se guardan como referencia: tiempo (ms) y x, y de los 7 puntos, con 4 decimales."""
    out = []
    for f in fotogramas:
        p = f.get("p") if isinstance(f, dict) else None
        if not p or len(p) < 7:
            continue
        out.append([int(f.get("t", 0))] + [round(float(v), 4) for punto in p[:7] for v in punto[:2]])
    return out
