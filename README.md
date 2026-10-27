# Axon-Pose

Sistema web que, con una cámara convencional, califica en tiempo real la ejecución de tres ejercicios de equilibrio en adultos mayores (posición en tándem, apoyo unipodal y postura del árbol) y le indica al paciente cómo corregirse con voz y texto.

Tesis: *Modelo de visión artificial de corrección de postura durante ejercicios de equilibrio en adultos mayores*, María Guisela Huanca Torrez, UPEA.

## Cómo funciona

1. En el navegador, MediaPipe Pose (complejidad 0) obtiene 33 puntos del cuerpo en cada fotograma. **No se envía ni se guarda video**: solo coordenadas.
2. Cada 0,5 s, `camera.js` envía el último segundo de puntos a `/api/analizar-pose/`.
3. En el servidor, `vision/clasificador.py`:
   - comprueba que el paciente esté en la postura (regla 1);
   - calcula 33 características con `vision/caracteristicas.py` (el mismo módulo usado en el entrenamiento);
   - decide con el modelo del ejercicio: SVM (núcleo RBF) en tándem y regresión logística en unipodal y árbol;
   - comprueba los brazos, permitiendo apoyar una mano en la silla (regla 2);
   - elige el error principal y el mensaje de corrección.
4. La página muestra el mensaje y lo dice en voz alta si el error se repite en 2 ventanas seguidas (como máximo cada 4 s).
5. Al terminar cada repetición de 20 s, `rutina.js` la guarda: es correcta si estuvo mal como mucho la mitad del tiempo.

## Estructura

| Ruta | Contenido |
|---|---|
| `axon/` | Configuración de Django (`settings.py`, `urls.py`) |
| `exercises/models.py` | Usuarios y perfiles, sesiones diarias, repeticiones, evaluaciones de Romberg, encuesta, consejos y citas |
| `exercises/views.py` | Páginas y API (`/api/analizar-pose/`, `/api/rutinas/<id>/repeticiones/`, `/api/rutinas/<id>/finalizar/`, `/api/romberg/`) |
| `exercises/vision/caracteristicas.py` | 16 medidas por fotograma y 33 características por ventana de 1 s |
| `exercises/vision/clasificador.py` | Reglas de postura y de brazos, modelo y mensaje de corrección |
| `exercises/vision/romberg.py` | Balanceo lateral de la evaluación de Romberg |
| `exercises/vision/modelos/*.json` | Modelos entrenados (tándem, unipodal, árbol), ejecutados en Python puro |
| `exercises/static/exercises/js/camera.js` | Cámara, MediaPipe, envío de puntos, mensajes y voz |
| `exercises/static/exercises/js/rutina.js` | Orden de los ejercicios, pierna, reloj, descansos y guardado |
| `exercises/templates/exercises/` | Plantillas HTML |
| `exercises/tests_modelo.py`, `tests_romberg.py` | Pruebas automáticas |

El entrenamiento está en la carpeta `Dataset` (scripts `extraer_puntos.py`, `proponer_tramos.py`, `construir_ventanas.py`, `entrenar.py`, con sus guías y la bitácora `BITACORA.md`).

## Instalación

Requisitos: Python 3.12 y PostgreSQL.

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Crear la base de datos `AXON-POSE` en PostgreSQL (los datos de conexión están en `axon/settings.py`) y luego:

```bash
python manage.py migrate
python manage.py createsuperuser   # este usuario entra como doctor
python manage.py runserver
```

Abrir `http://127.0.0.1:8000/` en Chrome o Edge y permitir el uso de la cámara.

## Pruebas

```bash
python manage.py test exercises
```

Son 23 pruebas: decisiones del clasificador con ventanas reales del conjunto de datos, persona parada, puntos incompletos, regla de brazos y apoyo en la silla, API, guardado de la rutina, progreso y PDF, y cálculo y registro del Romberg.

## Documentación

- `INTEGRACION_MODELO.md`: cómo se integró el clasificador en Django.
- `Dataset/BITACORA.md`: decisiones del proyecto (D1 en adelante), con su motivo.
- `Dataset/GUIA_EXTRACCION.md` y `Dataset/GUIA_ENTRENAMIENTO.md`: cómo repetir la extracción de puntos y el entrenamiento.
