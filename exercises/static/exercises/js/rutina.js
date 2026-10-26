(function initDailyRoutine() {
    const video = document.getElementById('webcam');
    const startButton = document.getElementById('btnStartEval');
    const stopButton = document.getElementById('btnStopEval');
    if (!video || !startButton || !stopButton) return;

    const exercises = [
        { value: 'Equilibrio Estatico', label: 'Equilibrio Estático' },
        { value: 'Soporte Monopodal', label: 'Soporte Monopodal' },
        { value: 'Marcha Tandem', label: 'Marcha Tándem' }
    ];
    const repetitionsPerExercise = 5;
    const restSeconds = 15;
    const sessionId = '{{ daily_session.id }}';
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
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

    function showTime(seconds) {
        timer.textContent = `00:${String(Math.max(seconds, 0)).padStart(2, '0')}`;
    }

    function updateHeader() {
        const exercise = exercises[exerciseIndex];
        label.textContent = `${exercise.label} · Repetición ${repetition + 1}/${repetitionsPerExercise}`;
        select.value = exercise.value;
        progress.style.width = `${((exerciseIndex * repetitionsPerExercise + repetition) /
            (exercises.length * repetitionsPerExercise)) * 100}%`;
    }

    function startCameraWork() {
        phase = 'work';
        state.textContent = '¡EJERCITANDO!';
        state.className = 'fw-bold text-success';
        updateHeader();
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
        const ok = Boolean(analysis && analysis.alineacionOptima);
        const response = await fetch(`/api/rutinas/${sessionId}/repeticiones/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({
                exerciseName: exercises[exerciseIndex].value,
                result: ok ? 'OK' : 'NOK',
                durationSec: 30,
                stabilityPct: Number(analysis?.estabilidad || 0),
                deviationCm: Number(analysis?.desviacionCm || 0)
            })
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'No se pudo guardar la repetición.');
        if (ok) success += 1; else failure += 1;
        document.getElementById('successCount').textContent = success;
        document.getElementById('failureCount').textContent = failure;
    }

    async function finishSession() {
        const response = await fetch(`/api/rutinas/${sessionId}/finalizar/`, {
            method: 'POST', headers: { 'X-CSRFToken': csrf }
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'No se pudo cerrar la sesión.');
        state.textContent = result.status === 'COMPLETADA' ? 'SESIÓN COMPLETADA' : 'SESIÓN INCOMPLETA';
        state.className = result.status === 'COMPLETADA' ? 'fw-bold text-success' : 'fw-bold text-danger';
        document.getElementById('sessionSummary').textContent =
            `Día {{ day_number }} guardado: ${success} éxitos y ${failure} fallos.`;
        running = false;
        video.dispatchEvent(new CustomEvent('axon:end-routine'));
        startButton.disabled = true;
        stopButton.disabled = true;
    }

    video.addEventListener('axon:pose-analysis', (event) => {
        latestAnalysis = event.detail;
    });
    video.addEventListener('axon:work-complete', async (event) => {
        if (!running || phase !== 'work') return;
        try {
            await registerRepetition(event.detail || latestAnalysis);
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
