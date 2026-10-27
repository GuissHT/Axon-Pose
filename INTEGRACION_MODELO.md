# Integración del clasificador de postura (26-oct-2026)

Rama sugerida: `integracion-modelo` (creada a partir de `main`, commit `0e1607f`).

## Qué hace ahora el sistema

1. La página captura la cámara y MediaPipe Pose (complejidad 0) obtiene 33 puntos por fotograma, en el navegador.
2. `camera.js` guarda **solo coordenadas** del último segundo (nunca video) y cada 0,5 s las envía a `/api/analizar-pose/`.
3. **Comprobación de posición** (`comprobar_posicion`): antes de calificar se verifica que la persona esté en la postura:
   tándem = tobillos casi en la misma vertical (pies en línea); unipodal y árbol = pie de trabajo levantado.
   Umbral estricto para entrar y tolerante para seguir dentro (histéresis); si no se ven los pies, pide alejarse. Si no, responde
   `fuera_de_posicion` con la indicación ("Coloque un pie delante del otro, en línea", "Levante el pie derecho"…).
   **El reloj de 20 s empieza recién cuando se detecta la postura.**
4. Django calcula 33 características (`vision/caracteristicas.py`, el mismo módulo del entrenamiento) y el clasificador decide:
   - **Tándem:** SVM con núcleo RBF.
   - **Apoyo unipodal y árbol:** regresión logística.
5. **Comprobación de brazos** (`comprobar_brazos`), brazo por brazo: tándem y unipodal = extendido al costado a la
   altura del hombro; árbol = sobre la cabeza o a la altura del hombro. **Basta con un brazo: el otro puede apoyarse
   en la silla.** Con los dos abajo, la ventana es incorrecta ("Levante los brazos a la altura de los hombros; puede
   apoyar una mano en la silla"). Se suma al modelo porque en
   el dataset nadie hizo los ejercicios con los brazos abajo.
6. Si es incorrecta, se elige el **mensaje de corrección** según la medida que más se aleja de las ejecuciones correctas
   ("Enderece el tronco", "Mire al frente", "No cruce las piernas", "Eleve más el pie", etc.).
7. Alerta **hablada** (voz del navegador, en español) solo si el error se repite en 2 ventanas seguidas, y como máximo cada 4 s.
8. En la rutina (**6 repeticiones de 20 s por ejercicio, 3 con cada pierna, alternando**), cada repetición se califica como **correcta si como mucho el 50 % de sus ventanas fue incorrecta**.
   Se guarda: pierna, ventanas analizadas, % incorrecto, error más frecuente, latencia media y FPS.

## Evaluación de Romberg (`vision/romberg.py`): medición de referencia

- **Inicial, obligatoria antes de la primera rutina** (la rutina lleva a la evaluación si falta). **Final, opcional**, al terminar el programa.
- Dos fases de 30 s (ojos abiertos y ojos cerrados). En vivo se ve el balanceo de los últimos 3 s y hacia qué lado.
- Al terminar, el servidor mide la amplitud del balanceo lateral y la guarda con los **puntos de referencia**. No decide si el paciente es apto.
- Si la cámara no vio bien a la persona, la evaluación queda como no válida y se repite.
- El doctor ve inicial, final y el cambio, y puede dejar una nota.
- Requiere `python manage.py migrate` (migraciones `0017` y `0018`).

## Dónde se ven los resultados

- **Romberg:** en Mi progreso, Seguimiento de pacientes (columna Romberg), panel del doctor y PDF.
- **Paciente → "Mi progreso":** sección "Rutina diaria" con los totales, un gráfico del % de repeticiones correctas por
  sesión, una tabla por ejercicio y pierna, y el detalle de cada repetición.
- **Doctor → "Seguimiento de pacientes":** rutinas y % de repeticiones correctas por paciente; "Ver detalles" abre su
  progreso completo. También aparece en el panel del doctor y en el PDF.

## Archivos

| Archivo | Cambio |
|---|---|
| `exercises/vision/caracteristicas.py` | **Nuevo.** Medidas posturales (Python puro), idéntico al de `Dataset/` |
| `exercises/vision/clasificador.py` | **Nuevo.** Ejecuta los modelos (Python puro, sin scikit-learn) y elige el mensaje |
| `exercises/vision/modelos/tandem.json`, `unipodal.json`, `arbol.json` | **Nuevos.** Modelos exportados del entrenamiento |
| `exercises/vision/modelos/ejemplos_prueba.json` | **Nuevo.** 6 ventanas reales del dataset para las pruebas |
| `exercises/tests_modelo.py` | **Nuevo.** Pruebas automáticas |
| `exercises/migrations/0016_postura_arbol_y_resultado_modelo.py` | **Nueva.** "Postura del Árbol" y campos del resultado del modelo |
| `exercises/models.py` | "Postura del Arbol" en las opciones; `ROUTINE_EXERCISES`; campos nuevos en `ExerciseRepetition` |
| `exercises/views.py` | `analizar_pose` usa el clasificador (antes importaba archivos que no existían); `registrar_repeticion` guarda el resultado del modelo; `finalizar_rutina` exige los 3 ejercicios de la rutina |
| `exercises/static/exercises/js/camera.js` | Envía ventanas de 1 s, alerta hablada con persistencia, latencia y FPS |
| `exercises/static/exercises/js/rutina.js` | Ejercicios: tándem, unipodal, árbol; pierna intercalada; calificación por el modelo; corrige `{{ daily_session.id }}` escrito en un archivo estático |
| `historial.html`, `progreso_pacientes.html`, `doctor_dashboard.html` | Resultados de la rutina en el progreso, el seguimiento y el panel |
| `exercises/templates/exercises/rutina_diaria.html` | Atributos `data-` (sesión, día, prueba, pierna), etiqueta de la pierna y opciones de ejercicio |

No se agregan dependencias: el clasificador es Python puro.

## Cómo probar (en la terminal de VS Code, carpeta `Axon-Pose`, con el entorno de Django activo)

```
git checkout -b integracion-modelo
python manage.py migrate
python manage.py test exercises
python manage.py runserver
```

- Las pruebas deben terminar en **OK** (23 pruebas).
- Luego entra como paciente a `http://127.0.0.1:8000/rutina-diaria/`, presiona **Comenzar ejercicio** y haz el tándem
  frente a la cámara. Si estás parada normal, el reloj se queda en 00:20 y te dice "Coloque un pie delante del otro";
  al ponerte en tándem dice "Posición correcta. Empezamos" y empieza el conteo. El mensaje cambia cada medio segundo y, si te inclinas, la voz dice "Enderece el tronco".

## Pendiente / a verificar

- **Si algo falla con la cámara:** presiona F12 → Consola. Ahí aparecen los errores y, en cada ventana, la línea
  `[Axon] posición …` con la separación de los tobillos y la elevación del pie (sirve para ajustar `POSICION`).
- **Comprobación de posición:** umbrales calibrados con el dataset (`POSICION` en `clasificador.py`). Grabar clips cortos
  de "parado normal", "pies juntos lado a lado" y "pie equivocado adelante" con la cámara de la página para confirmarlos.

- **Cámara de la página vs. dataset:** el modelo se entrenó con videos verticales de teléfono; la página usa cámara web
  horizontal (640×480). Las medidas están normalizadas, pero hay que comprobarlo en la prueba real.
- El badge "Día X de 15" y el límite de 15 días siguen como estaban (decisión pendiente: quitarlos).
- El árbol todavía acepta el pie sobre la rodilla en las reglas antiguas; el clasificador nuevo sí lo detecta como error.
- La evaluación de Romberg (`diagnostico.html`) mide el balanceo lateral con `vision/romberg.py`; no usa un clasificador.
