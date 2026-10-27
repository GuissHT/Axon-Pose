(function initDailyRoutine() {
    const video = document.getElementById('webcam');
    const startButton = document.getElementById('btnStartEval');
    const stopButton = document.getElementById('btnStopEval');
    if (!video || !startButton || !stopButton) return;

    // Los tres ejercicios de la tesis. 'Equilibrio Estatico' (Romberg) es solo evaluación.
    const allExercises = [
        { key: 'tandem', value: 'Marcha Tandem', label: 'Posición en tándem', short: 'Tándem' },
        { key: 'unipodal', value: 'Soporte Monopodal', label: 'Apoyo unipodal', short: 'Unipodal' },
        { key: 'arbol', value: 'Postura del Arbol', label: 'Postura del árbol', short: 'Árbol' }
    ];
    // La rutina empieza por el ejercicio desde el que se entró (?ejercicio=unipodal) y sigue con los
    // otros dos, para que la sesión del día tenga siempre los tres ejercicios.
    const requested = new URLSearchParams(window.location.search).get('ejercicio');
    const firstIndex = Math.max(allExercises.findIndex((e) => e.key === requested), 0);
    const exercises = allExercises.slice(firstIndex).concat(allExercises.slice(0, firstIndex));
    const stepsList = document.getElementById('routineSteps');

    function renderSteps(current) {
        if (!stepsList) return;
        stepsList.replaceChildren(...exercises.map((e, i) => {
            const li = document.createElement('li');
            li.textContent = `${i + 1}. ${e.short}`;
            if (i < current) li.className = 'done';
            else if (i === current) li.className = 'active';
            return li;
        }));
    }
    // 6 repeticiones de 20 s por ejercicio: 3 con cada pierna, alternando (der, izq, der, izq, der, izq).
    const repetitionsPerExercise = 6;
    const WORK_SECONDS = Number(video.dataset.durationSec) || 20;
    const restSeconds = 15;
    // Umbral para calificar la repetición: incorrecta si más de la mitad de las ventanas
    // de 1 s fueron clasificadas como incorrectas por el modelo.
    const INCORRECT_THRESHOLD_PCT = 50;
    // Antes se escribía '{{ daily_session.id }}' dentro de este archivo estático, y Django no lo
    // reemplazaba. Ahora el número de sesión y el día vienen de atributos data- de la plantilla.
    const sessionId = video.dataset.sessionId;
    const dayNumber = video.dataset.dayNumber || '';
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
    const sideLabel = document.getElementById('sideLabel');
    let exerciseIndex = 0;
    let repetition = 0;
    let phase = 'work';
    let latestAnalysis = null;
    let success = 0;
    let failure = 0;
    let countdown = null;
    let running = false;
    let cameraStarted = false;

    const state = document.getElementById('routineState');
    const timer = document.getElementById('routineTimer');
    const label = document.getElementById('exerciseLabel');
    const select = document.getElementById('testTypeSelect');
    const progress = document.getElementById('routineProgress');
    updateHeaderInitial();

    // Lee la respuesta sin romperse si el servidor devuelve HTML en lugar de JSON.
    async function readJson(response) {
        const text = await response.text();
        try {
            return JSON.parse(text);
        } catch (error) {
            return { ok: false, error: `Respuesta no válida del servidor (código ${response.status})` };
        }
    }

    function updateHeaderInitial() {
        renderSteps(0);
        label.textContent = exercises[0].label;
        select.value = exercises[0].value;
        video.dataset.testType = exercises[0].value;
        if (sideLabel) {
            sideLabel.textContent = sideInstruction();
        }
    }

    function showTime(seconds) {
        timer.textContent = `00:${String(Math.max(seconds, 0)).padStart(2, '0')}`;
    }

    // Pierna que trabaja, intercalada: repeticiones impares derecha, pares izquierda.
    function currentSide() {
        return repetition % 2 === 0 ? 'der' : 'izq';
    }

    function updateHeader() {
        const exercise = exercises[exerciseIndex];
        const side = currentSide();
        label.textContent = `${exercise.label} · Repetición ${repetition + 1}/${repetitionsPerExercise}`;
        select.value = exercise.value;
        video.dataset.testType = exercise.value;
        video.dataset.side = side;
        if (sideLabel) sideLabel.textContent = sideInstruction();
        renderSteps(exerciseIndex);
        progress.style.width = `${((exerciseIndex * repetitionsPerExercise + repetition) /
            (exercises.length * repetitionsPerExercise)) * 100}%`;
    }

    // Qué pierna toca, en palabras para la pantalla y para la voz.
    function sideInstruction() {
        const pie = currentSide() === 'der' ? 'derecho' : 'izquierdo';
        const pierna = currentSide() === 'der' ? 'derecha' : 'izquierda';
        return {
            'Marcha Tandem': `Ponga el pie ${pie} adelante`,
            'Soporte Monopodal': `Levante la pierna ${pierna}`,
            'Postura del Arbol': `Doble la pierna ${pierna}`
        }[exercises[exerciseIndex].value] || '';
    }

    function announce(text) {
        if (!('speechSynthesis' in window)) return;
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'es-ES';
        utterance.rate = 0.95;
        window.speechSynthesis.speak(utterance);
    }

    function startCameraWork() {
        phase = 'work';
        showTime(WORK_SECONDS);
        // El reloj empieza cuando el modelo confirma la postura (evento axon:posture-ready).
        state.textContent = 'COLÓQUESE EN POSICIÓN';
        state.className = 'fw-bold text-warning';
        updateHeader();
        // Al inicio de cada repetición se dice con qué pie o pierna empezar.
        const instruccion = sideInstruction();
        if (sideLabel) sideLabel.textContent = instruccion;
        announce(`${exercises[exerciseIndex].label}, repetición ${repetition + 1}. ${instruccion}`);
        if (cameraStarted) {
            video.dispatchEvent(new CustomEvent('axon:resume-work'));
        } else {
            cameraStarted = true;
            video.dispatchEvent(new CustomEvent('axon:start-work'));
        }
    }

    function startRest() {
        phase = 'rest';
        state.textContent = 'DESCANSO';
        state.className = 'fw-bold text-warning';
        if (countdown) {
            window.clearInterval(countdown);
        }
        let remaining = restSeconds;
        showTime(remaining);
        countdown = window.setInterval(() => {
            remaining -= 1;
            showTime(remaining);
            if (remaining <= 0) {
                window.clearInterval(countdown);
                countdown = null;
                startCameraWork();
            }
        }, 1000);
    }

    async function registerRepetition(analysis) {
        const modelo = analysis && analysis.modelo;
        let ok;
        if (modelo && modelo.windows > 0) {
            ok = modelo.incorrectPct <= INCORRECT_THRESHOLD_PCT;
        } else {
            ok = Boolean(analysis && analysis.alineacionOptima);
        }
        const response = await fetch(`/api/rutinas/${sessionId}/repeticiones/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({
                exerciseName: exercises[exerciseIndex].value,
                result: ok ? 'OK' : 'NOK',
                durationSec: WORK_SECONDS,
                stabilityPct: Math.min(Math.max(Number(analysis?.estabilidad || 0), 0), 100),
                deviationCm: Math.max(Number(analysis?.desviacionCm || 0), 0),
                side: currentSide(),
                modelWindows: modelo ? modelo.windows : 0,
                modelIncorrectPct: modelo ? Number(modelo.incorrectPct.toFixed(2)) : 0,
                mainError: modelo ? modelo.mainError : '',
                latencyMs: modelo ? Number(modelo.latencyMs.toFixed(2)) : 0,
                fps: modelo ? Number(modelo.fps.toFixed(2)) : 0
            })
        });
        const result = await readJson(response);
        // El conteo se actualiza aunque falle el guardado, para no perder el avance en pantalla.
        if (ok) success += 1; else failure += 1;
        document.getElementById('successCount').textContent = success;
        document.getElementById('failureCount').textContent = failure;
        if (!response.ok || !result.ok) throw new Error(result.error || 'No se pudo guardar la repetición.');
        document.getElementById('successCount').textContent = success;
        document.getElementById('failureCount').textContent = failure;
    }

    async function finishSession() {
        const response = await fetch(`/api/rutinas/${sessionId}/finalizar/`, {
            method: 'POST', headers: { 'X-CSRFToken': csrf }
        });
        const result = await readJson(response);
        if (!response.ok || !result.ok) throw new Error(result.error || 'No se pudo cerrar la sesión.');
        renderSteps(exercises.length);
        state.textContent = result.status === 'COMPLETADA' ? 'SESIÓN COMPLETADA' : 'SESIÓN INCOMPLETA';
        state.className = result.status === 'COMPLETADA' ? 'fw-bold text-success' : 'fw-bold text-danger';
        document.getElementById('sessionSummary').textContent =
            `Día ${dayNumber} guardado: ${success} éxitos y ${failure} fallos.`;
        running = false;
        video.dispatchEvent(new CustomEvent('axon:end-routine'));
        startButton.disabled = true;
        stopButton.disabled = true;
    }

    video.addEventListener('axon:tick', (event) => {
        if (phase === 'work' && running) {
            showTime(event.detail.remaining);
        }
    });

    video.addEventListener('axon:posture-ready', () => {
        if (phase === 'work' && running) {
            state.textContent = '¡EJERCITANDO!';
            state.className = 'fw-bold text-success';
        }
    });

    video.addEventListener('axon:pose-analysis', (event) => {
        latestAnalysis = event.detail;
    });
    video.addEventListener('axon:work-complete', async (event) => {
        if (!running || phase !== 'work') return;
        try {
            try {
                await registerRepetition(event.detail || latestAnalysis);
            } catch (saveError) {
                // Se avisa pero la rutina sigue (antes se detenía y la pantalla quedaba congelada).
                console.warn('No se guardó la repetición:', saveError);
                document.getElementById('sessionSummary').innerHTML =
                    `<div class="alert alert-warning py-2 small mb-0">No se guardó una repetición: ${saveError.message}</div>`;
            }
            repetition += 1;
            latestAnalysis = null;
            if (repetition >= repetitionsPerExercise) {
                repetition = 0;
                exerciseIndex += 1;
            }
            if (exerciseIndex >= exercises.length) {
                await finishSession();
            } else {
                startRest();
            }
        } catch (error) {
            running = false;
            cameraStarted = false;
            video.dispatchEvent(new CustomEvent('axon:end-routine'));
            state.textContent = 'ERROR DE GUARDADO';
            state.className = 'fw-bold text-danger';
            alert(error.message);
        }
    });

    video.addEventListener('axon:start-failed', () => {
        running = false;
        cameraStarted = false;
        startButton.disabled = false;
        stopButton.disabled = true;
        state.textContent = 'NO SE PUDO INICIAR';
        state.className = 'fw-bold text-danger';
    });

    startButton.addEventListener('click', () => {
        if (running) return;
        running = true;
        exerciseIndex = 0;
        repetition = 0;
        success = 0;
        failure = 0;
        stopButton.disabled = false;
        startCameraWork();
    });

    stopButton.addEventListener('click', () => {
        running = false;
        if (countdown) window.clearInterval(countdown);
        countdown = null;
        video.dispatchEvent(new CustomEvent('axon:end-routine'));
        cameraStarted = false;
        state.textContent = 'SESIÓN DETENIDA';
        state.className = 'fw-bold text-danger';
        startButton.disabled = false;
        stopButton.disabled = true;
    });
})();
