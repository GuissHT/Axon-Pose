# -*- coding: utf-8 -*-
"""
clasificador.py - Proyecto Axon-Pose (tesis MGHT)

Clasifica una ventana de ~1 s de puntos de MediaPipe como CORRECTA o INCORRECTA y elige el mensaje
de correccion. Python puro (sin NumPy ni scikit-learn): los modelos estan en vision/modelos/*.json,
exportados desde el entrenamiento (Dataset/entrenar.py) del 26-oct-2026.

Modelos elegidos (decision D1 de la bitacora):
    tandem   -> SVM con nucleo RBF
    unipodal -> regresion logistica
    arbol    -> regresion logistica

Orden de la decision para una ventana (funcion clasificar):
    1. comprobar_posicion: si la persona no esta en la postura, se responde como colocarse.
    2. caracteristicas: las 33 medidas de la ventana (mismo modulo que el entrenamiento).
    3. modelo: correcto o incorrecto.
    4. comprobar_brazos: los dos brazos abajo tambien es incorrecto.
    5. mensaje: la medida que mas se aleja (en desviaciones estandar) de las ventanas correctas, en la
       direccion del error (catalogo ETIQUETAS_ERRORES.md), o el mensaje de brazos.
"""
import json
import math
import os
import time

from . import caracteristicas as C

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos")
_CACHE = {}
MIN_VALIDOS = 0.7
MIN_FOTOGRAMAS = 8

# Nombre de la prueba en el sistema -> clave del modelo
EJERCICIOS = {
    "Marcha Tandem": "tandem",
    "Soporte Monopodal": "unipodal",
    "Postura del Arbol": "arbol",
}

# (caracteristica, direccion del error: +1 = valores altos son error, -1 = valores bajos, etiqueta)
# Seleccion ajustada el 26-oct con las 959 ventanas incorrectas etiquetadas por la fisioterapeuta
# (se quitaron reglas que empeoraban la coincidencia: asimetria de brazos y altura de la nariz).
_COMUNES = [
    ("tronco_lateral_g_media", +1, "tronco_inclinado"),
    ("hombros_incl_g_media", +1, "tronco_inclinado"),
    ("tronco_vertical_media", -1, "tronco_adelante"),
    ("orejas_altura_media", -1, "cabeza_abajo"),
    ("brazos_altura_media", +1, "brazos_elevados"),
    ("pie_lado_media", -1, "pierna_cruzada"),
    ("oscilacion_centro", +1, "perdida_equilibrio"),
]
REGLAS_MENSAJE = {
    "tandem": _COMUNES + [("rodilla_lado_media", -1, "pierna_cruzada"),
                          ("tobillos_separacion_media", +1, "pies_separados")],
    "unipodal": _COMUNES + [("rodilla_lado_media", -1, "pierna_cruzada"),
                            ("pie_elevacion_media", -1, "pie_bajo"),
                            ("tobillo_trabajo_vis_media", -1, "pie_detras")],
    "arbol": _COMUNES + [("pie_elevacion_media", -1, "pie_en_suelo"),
                         ("pie_vs_rodilla_media", +1, "pie_sobre_rodilla")],
}


# -----------------------------------------------------------------------------
# Regla 1: ¿la persona esta en la postura? (bitacora D18-D25)
# El clasificador solo aprendio a distinguir un ejercicio bien hecho de uno mal hecho; nunca vio a
# alguien parado sin hacerlo. Esta regla se aplica antes del modelo.
#   tandem: tobillos casi en la misma vertical (separacion lateral en anchos de hombros).
#   unipodal y arbol: pie de trabajo levantado (fraccion del largo de la pierna de apoyo).
# Dos umbrales (histeresis): uno estricto para entrar y uno tolerante para seguir dentro, para que el
# ruido de un fotograma no saque a la persona de la postura. Calibrados con el dataset.
# -----------------------------------------------------------------------------
POSICION = {
    "tandem_sep_entrar": 0.15,
    "tandem_sep_seguir": 0.22,
    "tandem_pie_mal_dz": 0.15,
    "tandem_pie_mal_dy": -0.06,
    "elev_entrar": 0.08,
    "elev_seguir": 0.04,
    "vis_tobillos_min": 0.3,
}
_LADO_TXT = {"der": "derecho", "izq": "izquierdo"}
_OTRO = {"der": "izq", "izq": "der"}


def _mediana(vals):
    vals = sorted(v for v in vals if v == v)
    if not vals:
        return float("nan")
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def comprobar_posicion(clave, puntos_fotogramas, ancho, alto, lado, ya_en_posicion=False):
    """Devuelve (en_posicion, mensaje, medidas). puntos_fotogramas: listas de 33 (x,y,z,v).
    ya_en_posicion: True si la ventana anterior ya estaba en la postura (umbral mas tolerante)."""
    T = {"der": 28, "izq": 27}  # tobillos
    CAD = {"der": 24, "izq": 23}
    sep, dy, dz, elev, vis = [], [], [], [], []
    for lm in puntos_fotogramas:
        if lm[11][3] < 0.5 or lm[12][3] < 0.5:
            continue
        sw = math.hypot((lm[11][0] - lm[12][0]) * ancho, (lm[11][1] - lm[12][1]) * alto)
        if sw < 1:
            continue
        f, b = T[lado], T[_OTRO[lado]]
        vis.append(min(lm[27][3], lm[28][3]))
        sep.append(abs(lm[27][0] - lm[28][0]) * ancho / sw)
        dy.append((lm[f][1] - lm[b][1]) * alto / sw)
        dz.append(lm[f][2] - lm[b][2])
        ca = CAD[_OTRO[lado]]
        pierna = math.hypot((lm[ca][0] - lm[b][0]) * ancho, (lm[ca][1] - lm[b][1]) * alto) or 1.0
        elev.append((lm[b][1] - lm[f][1]) * alto / pierna)
    m = {"separacion": _mediana(sep), "dy": _mediana(dy), "dz": _mediana(dz),
         "elevacion": _mediana(elev), "visibilidad_pies": _mediana(vis)}
    if m["separacion"] != m["separacion"]:
        return False, "Colóquese de cuerpo entero frente a la cámara", m
    if m["visibilidad_pies"] < POSICION["vis_tobillos_min"]:
        return False, "Aléjese un poco: la cámara debe ver sus pies", m
    t = _LADO_TXT[lado]
    if clave == "tandem":
        limite = POSICION["tandem_sep_seguir" if ya_en_posicion else "tandem_sep_entrar"]
        if m["separacion"] >= limite:
            return False, "Coloque un pie delante del otro, en línea", m
        if (not ya_en_posicion and m["dz"] > POSICION["tandem_pie_mal_dz"]
                and m["dy"] < POSICION["tandem_pie_mal_dy"]):
            return False, "Ponga el pie %s adelante" % t, m
        return True, "", m
    # unipodal y arbol: el pie de trabajo debe estar levantado
    limite = POSICION["elev_seguir" if ya_en_posicion else "elev_entrar"]
    if m["elevacion"] > limite:
        return True, "", m
    if m["elevacion"] < -POSICION["elev_entrar"]:
        return False, "Levante el pie %s, no el otro" % t, m
    if clave == "arbol":
        return False, "Apoye la planta del pie %s en el tobillo o la pantorrilla" % t, m
    return False, "Levante el pie %s" % t, m


# -----------------------------------------------------------------------------
# Regla 2: brazos, con apoyo en la silla permitido (bitacora D28-D32)
# En el dataset nadie hizo los ejercicios con los dos brazos abajo, asi que el modelo no aprendio ese
# caso. Se evalua cada brazo por separado y basta con que UNO este en posicion; el otro puede estar
# apoyado en la silla.
#   tandem y unipodal: brazo extendido al costado, a la altura del hombro.
#   arbol: brazo a la altura del hombro o sobre la cabeza.
# Con apoyo, las medidas de brazos que usa el modelo se reemplazan por sus valores tipicos en las
# ejecuciones correctas, para que el modelo juzgue solo el resto del cuerpo.
# Calibrada con el dataset: no marca como incorrectas las ventanas correctas (1 de 1026).
# -----------------------------------------------------------------------------
BRAZOS = {
    "altura_min": -0.8,       # brazo en posicion (tandem, unipodal)
    "altura_max": 0.5,
    "afuera_min": 0.55,
    "elevado": 0.6,           # un brazo por encima: brazos elevados
    "arbol_altura_min": -0.5,
    "visibilidad_min": 0.5,   # un brazo que no se ve no se juzga (cuenta como apoyo)
    "z_modelo_prioridad": 3.0,  # si el clasificador encontro un error claro (z >= 3), se dice ese primero
}
_FEATS_BRAZOS = ("brazos_altura_media", "brazos_altura_desv", "brazos_asimetria_media", "brazos_asimetria_desv")
_APOYO = "puede apoyar una mano en la silla"
MENSAJES_BRAZOS = {
    "brazos_abajo": "Levante los brazos a la altura de los hombros; " + _APOYO,
    "brazos_abajo_arbol": "Levante los brazos; " + _APOYO,
    "brazos_recogidos": "Extienda los brazos a los lados; " + _APOYO,
    "brazos_elevados": "Baje los brazos a la altura de los hombros",
}


def comprobar_brazos(clave, puntos_fotogramas, ancho, alto):
    """Devuelve (error o None, medidas). Mide cada brazo por separado."""
    h = {15: [], 16: []}
    afuera = {15: [], 16: []}
    vis = {15: [], 16: []}
    for lm in puntos_fotogramas:
        sw = math.hypot((lm[11][0] - lm[12][0]) * ancho, (lm[11][1] - lm[12][1]) * alto)
        if sw < 1 or lm[11][3] < 0.5 or lm[12][3] < 0.5:
            continue
        for hombro, otro, muneca in ((11, 12, 15), (12, 11, 16)):
            signo = 1.0 if lm[hombro][0] >= lm[otro][0] else -1.0
            h[muneca].append((lm[hombro][1] - lm[muneca][1]) * alto / sw)
            afuera[muneca].append((lm[muneca][0] - lm[hombro][0]) * signo * ancho / sw)
            vis[muneca].append(lm[muneca][3])
    m = {}
    for muneca, nombre in ((15, "izq"), (16, "der")):
        m["altura_" + nombre] = _mediana(h[muneca])
        m["afuera_" + nombre] = _mediana(afuera[muneca])
        m["visibilidad_" + nombre] = _mediana(vis[muneca])
    visibles = [n for n in ("izq", "der")
                if m["altura_" + n] == m["altura_" + n] and m["visibilidad_" + n] >= BRAZOS["visibilidad_min"]]
    if not visibles:
        return None, m
    if clave != "arbol" and any(m["altura_" + n] > BRAZOS["elevado"] for n in visibles):
        return "brazos_elevados", m

    def en_posicion(n):
        a = m["altura_" + n]
        if clave == "arbol":
            return a >= BRAZOS["arbol_altura_min"]
        return BRAZOS["altura_min"] <= a <= BRAZOS["altura_max"] and m["afuera_" + n] >= BRAZOS["afuera_min"]

    if len(visibles) < 2 or any(en_posicion(n) for n in visibles):
        # al menos un brazo en posicion; si el otro no lo esta, se considera apoyado en la silla
        m["apoyo"] = not (len(visibles) == 2 and all(en_posicion(n) for n in visibles))
        return None, m
    if clave == "arbol":
        return "brazos_abajo", m
    if all(m["altura_" + n] >= BRAZOS["altura_min"] for n in visibles):
        return "brazos_recogidos", m
    return "brazos_abajo", m


def _mensaje_brazos(clave, error):
    if clave == "arbol" and error == "brazos_abajo":
        return MENSAJES_BRAZOS["brazos_abajo_arbol"]
    return MENSAJES_BRAZOS[error]


def cargar(clave):
    if clave not in _CACHE:
        with open(os.path.join(_DIR, clave + ".json"), encoding="utf-8") as fh:
            _CACHE[clave] = json.load(fh)
    return _CACHE[clave]


def _vector(modelo, feats):
    x = []
    for i, nombre in enumerate(modelo["caracteristicas"]):
        val = feats.get(nombre, float("nan"))
        if val is None or val != val:  # NaN -> mediana del entrenamiento
            val = modelo["mediana_imputacion"][i]
        esc = modelo["escala"][i] or 1.0
        x.append((val - modelo["media"][i]) / esc)
    return x


def _puntaje(modelo, x):
    """Devuelve (es_incorrecto, puntaje). Puntaje > 0 significa incorrecto."""
    if modelo["tipo"] == "svm_rbf":
        g = modelo["gamma"]
        s = modelo["intercepto"]
        for sv, a in zip(modelo["vectores_soporte"], modelo["coef_dual"]):
            d2 = sum((xi - si) ** 2 for xi, si in zip(x, sv))
            s += a * math.exp(-g * d2)
        return s > 0, s
    z = modelo["intercepto"] + sum(c * xi for c, xi in zip(modelo["coef"], x))
    return z > 0, z


def _probabilidad(modelo, puntaje):
    if modelo["tipo"] == "svm_rbf":
        return None  # la SVM no da probabilidad; se informa el puntaje
    # sigmoide estable (evita OverflowError con puntajes muy grandes)
    if puntaje >= 0:
        return 1.0 / (1.0 + math.exp(-puntaje))
    e = math.exp(puntaje)
    return e / (1.0 + e)


def _error_principal(clave, modelo, feats):
    ref = modelo["referencia_correctos"]
    mejor, mejor_z = None, 0.0
    for nombre, dirc, etiqueta in REGLAS_MENSAJE[clave]:
        v = feats.get(nombre)
        r = ref.get(nombre)
        if v is None or v != v or not r or not r["desv"] or r["desv"] != r["desv"]:
            continue
        z = dirc * (v - r["media"]) / r["desv"]
        if z > mejor_z:
            mejor, mejor_z = etiqueta, z
    return mejor, mejor_z


def _num(v, nd=4):
    """Numero apto para JSON: NaN o infinito -> None."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return round(v, nd)


def _normalizar_puntos(lm):
    """Acepta [[x,y,z,v],...] o [{'x':..,'y':..,'z':..,'visibility':..},...]."""
    out = []
    for p in lm:
        if isinstance(p, dict):
            out.append((float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("z", 0)),
                        float(p.get("visibility", p.get("v", 1.0)))))
        else:
            v = p[3] if len(p) > 3 else 1.0
            out.append((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0, float(v)))
    return out


def clasificar(prueba, fotogramas, ancho, alto, lado="der", ya_en_posicion=False):
    """
    prueba: nombre de la prueba ('Marcha Tandem', 'Soporte Monopodal', 'Postura del Arbol').
    fotogramas: lista (~1 s) de listas de 33 puntos.
    ancho, alto: tamano del video en pixeles. lado: 'der' o 'izq' (pierna que trabaja).
    ya_en_posicion: la pagina avisa si la ventana anterior ya estaba en la postura.
    """
    t0 = time.perf_counter()
    clave = EJERCICIOS.get(prueba)
    if clave is None:
        raise ValueError("No hay modelo para la prueba: %s" % prueba)
    if lado not in ("der", "izq"):
        lado = "der"
    modelo = cargar(clave)
    medidas = []
    for lm in fotogramas:
        if lm and len(lm) >= 33:
            medidas.append(C.fotograma(_normalizar_puntos(lm), float(ancho), float(alto), lado))
    validos = [m for m in medidas if m]
    if len(validos) < MIN_FOTOGRAMAS or len(validos) < MIN_VALIDOS * max(len(fotogramas), 1):
        return {
            "valido": False,
            "en_posicion": False,
            "incorrecto": False,
            "mensaje": "Colóquese de cuerpo entero frente a la cámara",
            "error": None,
            "fotogramas_validos": len(validos),
            "ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    puntos = [_normalizar_puntos(lm) for lm in fotogramas if lm and len(lm) >= 33]
    en_pos, msg_pos, med_pos = comprobar_posicion(clave, puntos, float(ancho), float(alto), lado, bool(ya_en_posicion))
    if not en_pos:
        return {
            "valido": True,
            "en_posicion": False,
            "incorrecto": True,
            "estado": "fuera_de_posicion",
            "error": "fuera_de_posicion",
            "mensaje": msg_pos,
            "modelo": modelo["tipo"],
            "posicion": {k: _num(v, 3) for k, v in med_pos.items()},
            "fotogramas_validos": len(validos),
            "ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    feats = C.ventana(validos)
    error_brazos, med_brazos = comprobar_brazos(clave, puntos, float(ancho), float(alto))
    if med_brazos.get("apoyo"):
        ref = modelo["referencia_correctos"]
        for f in _FEATS_BRAZOS:
            if f in feats and f in ref:
                feats[f] = ref[f]["media"]
    incorrecto, puntaje = _puntaje(modelo, _vector(modelo, feats))
    error, z = _error_principal(clave, modelo, feats) if incorrecto else (None, 0.0)
    incorrecto_modelo = bool(incorrecto)
    mensaje_extra = ""
    if error_brazos:
        if not incorrecto or error is None or z < BRAZOS["z_modelo_prioridad"]:
            error = error_brazos
        else:
            # El modelo encontro otro error claro: se dicen los dos (primero el del modelo).
            mensaje_extra = ". " + _mensaje_brazos(clave, error_brazos)
    incorrecto = incorrecto or bool(error_brazos)
    if error == error_brazos and error_brazos:
        mensaje = _mensaje_brazos(clave, error)
    elif incorrecto:
        mensaje = C.MENSAJES.get(error, "Corrija la postura") + mensaje_extra
    else:
        mensaje = "Muy bien, mantenga la postura"
    prob = _probabilidad(modelo, puntaje)
    return {
        "valido": True,
        "en_posicion": True,
        "posicion": {k: _num(v, 3) for k, v in med_pos.items()},
        "incorrecto": bool(incorrecto),
        "estado": "incorrecto" if incorrecto else "correcto",
        "error": error,
        "incorrecto_modelo": incorrecto_modelo,
        "error_brazos": error_brazos,
        "apoyo_silla": bool(med_brazos.get("apoyo")),
        "brazos": {k: _num(v, 3) for k, v in med_brazos.items() if k != "apoyo"},
        "mensaje": mensaje,
        "modelo": modelo["tipo"],
        "puntaje": _num(puntaje),
        "probabilidad_incorrecto": _num(prob),
        "desvio_error": _num(z, 2),
        "medidas": {
            "tronco_lateral_g": _num(feats["tronco_lateral_g_media"], 1),
            "hombros_incl_g": _num(feats["hombros_incl_g_media"], 1),
            "rodilla_apoyo_g": _num(feats["rodilla_apoyo_g_media"], 1),
            "pie_elevacion": _num(feats["pie_elevacion_media"], 3),
            "oscilacion": _num(feats["oscilacion_centro"]),
        },
        "fotogramas_validos": len(validos),
        "ms": round((time.perf_counter() - t0) * 1000, 2),
    }
