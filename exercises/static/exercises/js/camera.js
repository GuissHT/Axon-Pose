/*
   Cámara y MediaPipe Pose, compartido por dos páginas:

   - Rutina diaria (rutina_diaria.html + rutina.js): en tándem, unipodal y árbol envía cada 0,5 s el
     último segundo de puntos a /api/analizar-pose/, donde el clasificador decide si la postura es
     correcta y devuelve el mensaje. Voz si el error se repite en 2 ventanas seguidas (máx. cada 4 s).
   - Evaluación de Romberg (diagnostico.html): dos fases de 30 s (ojos abiertos y cerrados). Muestra el
     balanceo en vivo, guarda 7 puntos por fotograma y al terminar los envía a /api/romberg/, que mide
     el balanceo y lo guarda como referencia (inicial o final; no decide si el paciente es apto).

   Nunca se envía ni se guarda video: solo coordenadas.
*/

(function initAxonPoseCameraModule() {
    const videoElement = document.getElementById('webcam');
    const canvasElement = document.getElementById('output_canvas');
    const btnStart = document.getElementById('btnStartEval');
    const btnStop = document.getElementById('btnStopEval');

    if (!videoElement || !canvasElement || !btnStart || !btnStop) {
        return;
    }

    const ctx = canvasElement.getContext('2d');
    const timerLabel = document.getElementById('timerLabel');
    const progressBar = document.getElementById('testProgress');
    const phaseIndicator = document.getElementById('phaseIndicator');
    const phaseNotice = document.getElementById('phaseNotice');
    const metricSway = document.getElementById('metricSway');
    const metricSide = document.getElementById('metricSide');
    const metricAngle = document.getElementById('metricAngle');
    const rombergResult = document.getElementById('rombergResult');
    const badgeCamera = document.getElementById('badgeCamera');
    const badgeAlignment = document.getElementById('badgeAlignment');
    // La prueba activa la define la página (data-test-type en el video) o la rutina (rutina.js).
    function getTestType() {
        return videoElement.dataset.testType || 'Equilibrio Estatico';
    }
    function getSide() {
        return videoElement.dataset.side === 'izq' ? 'izq' : 'der';
    }
    const MODEL_TESTS = new Set(['Marcha Tandem', 'Soporte Monopodal', 'Postura del Arbol']);
    const isRoutine = document.body.dataset.routine === 'true';
    const evaluationType = document.body.dataset.evaluationType || 'INICIAL';

    // Duración de cada repetición: la rutina usa 20 s (data-duration-sec); la evaluación, 30 s por fase.
    const TEST_DURATION_SECONDS = Number(videoElement.dataset.durationSec) || 30;
    const DURATION_TEXT = `00:${String(TEST_DURATION_SECONDS).padStart(2, '0')}`;
    const TOTAL_PHASES = 2;
    let streamRef = null;
    let poseRef = null;
    let animationRef = null;
    let isRunning = false;
    let workActive = false;
    let frameInFlight = false;
    let startInFlight = false;
    let evaluationStartedAt = 0;
    let currentPhase = 1;
    let latestAnalysis = null;
    let pythonAnalysisInFlight = false;
    let lastPythonAnalysisAt = 0;
    let lastAlertAt = 0;
    const PYTHON_ANALYSIS_INTERVAL_MS = 500;   // una decisión cada 0,5 s
    const ALERT_INTERVAL_MS = 1500;
    const WINDOW_MS = 1000;                    // ventana de 1 s, igual que en el entrenamiento
    const SPEECH_PERSISTENCE = 2;              // hablar solo si el error se repite en 2 ventanas seguidas
    const SPEECH_MIN_INTERVAL_MS = 4000;       // y como máximo cada 4 s
    const frameBuffer = [];                    // [{t, lm}] últimos fotogramas (solo coordenadas, sin video)
    let consecutiveIncorrect = 0;
    let lastSpeechAt = 0;
    let modelStats = null;
    // Comprobación de posición: en tándem, unipodal y árbol el conteo de 30 s empieza recién cuando
    // el servidor confirma que la persona está en la postura (antes contaba con solo estar parada).
    let postureReady = true;
    // Romberg: los 7 puntos que usa vision/romberg.py (nariz, hombros, caderas, tobillos)
    const ROMBERG_POINTS = [0, 11, 12, 23, 24, 27, 28];
    const ROMBERG_LIVE_MS = 3000;              // balanceo en vivo: últimos 3 s
    const rombergFrames = { 1: [], 2: [] };    // fase 1 = ojos abiertos, fase 2 = ojos cerrados

    function resetModelStats(keepBuffer) {
        modelStats = {
            windows: 0, incorrect: 0, errors: {}, latencies: [], frames: 0,
            startedAt: performance.now()
        };
        if (!keepBuffer) frameBuffer.length = 0;
        consecutiveIncorrect = 0;
    }
    resetModelStats();

    // Se llama al empezar cada repetición o fase: los ejercicios del modelo esperan la postura.
    function armPostureGate() {
        postureReady = !MODEL_TESTS.has(getTestType());
    }

    function summarizeModelStats() {
        if (!modelStats) return null;
        const elapsed = (performance.now() - modelStats.startedAt) / 1000;
        const lat = modelStats.latencies;
        let mainError = '';
        let best = 0;
        Object.entries(modelStats.errors).forEach(([key, count]) => {
            if (count > best) { best = count; mainError = key; }
        });
        return {
            windows: modelStats.windows,
            incorrectPct: modelStats.windows ? (100 * modelStats.incorrect / modelStats.windows) : 0,
            mainError,
            latencyMs: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : 0,
            fps: elapsed > 0 ? modelStats.frames / elapsed : 0
        };
    }

    function speak(text, force) {
        const now = performance.now();
        if (!force && now - lastSpeechAt < SPEECH_MIN_INTERVAL_MS) return;
        lastSpeechAt = now;
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'es-ES';
            utterance.rate = 0.95;
            window.speechSynthesis.speak(utterance);
        } else {
            playAlert();
        }
    }

    function playAlert() {
        const now = performance.now();
        if (now - lastAlertAt < ALERT_INTERVAL_MS) {
            return;
        }
        lastAlertAt = now;
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) {
            return;
        }
        const audioContext = new AudioContextClass();
        const oscillator = audioContext.createOscillator();
        const gain = audioContext.createGain();
        oscillator.frequency.value = 880;
        oscillator.type = 'sine';
        gain.gain.value = 0.08;
        oscillator.connect(gain);
        gain.connect(audioContext.destination);
        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.18);
        oscillator.addEventListener('ended', () => audioContext.close());
    }

    function getCsrfToken() {
        const tokenElement = document.querySelector('meta[name="csrf-token"]');
        const templateToken = tokenElement ? tokenElement.getAttribute('content') : '';
        if (templateToken) {
            return templateToken;
        }

        const cookies = document.cookie ? document.cookie.split(';') : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith('csrftoken=')) {
                return decodeURIComponent(trimmed.substring('csrftoken='.length));
            }
        }
        return '';
    }

    // Lee la respuesta del servidor sin romperse si no es JSON (p. ej. una página de error HTML).
    async function readJson(response) {
        const text = await response.text();
        try {
            return JSON.parse(text);
        } catch (error) {
            return { ok: false, error: `Respuesta no válida del servidor (código ${response.status})` };
        }
    }

    function setAnalysisStatus(message, isError) {
        badgeAlignment.textContent = message;
        badgeAlignment.classList.toggle('warning', Boolean(isError));
        badgeAlignment.classList.toggle('success', !isError);
    }

    // Muestra el resultado de la evaluación de Romberg (los textos vienen del servidor como datos).
    function showRombergResult(kind, title, lines) {
        if (!rombergResult) return;
        rombergResult.replaceChildren();
        const box = document.createElement('div');
        box.className = `alert alert-${kind} rounded-4 mb-0`;
        const strong = document.createElement('strong');
        strong.textContent = title;
        box.appendChild(strong);
        lines.forEach((text) => {
            const div = document.createElement('div');
            div.className = 'small mt-1';
            div.textContent = text;
            box.appendChild(div);
        });
        rombergResult.appendChild(box);
    }

    function describePhase(name, phase) {
        if (!phase || phase.amplitud_cm === null || phase.amplitud_cm === undefined) {
            return `${name}: no se pudo medir.`;
        }
        const side = phase.lado && phase.lado !== 'centro' ? `, hacia la ${phase.lado}` : '';
        return `${name}: balanceo de ${phase.amplitud_cm} cm${side} (${phase.pct_utiles} % de fotogramas útiles).`;
    }

    // Al terminar las dos fases se envían los puntos; el servidor calcula y guarda la sugerencia.
    async function enviarRomberg() {
        showRombergResult('info', 'Calculando el resultado...', []);
        try {
            const response = await fetch('/api/romberg/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({
                    evaluationType,
                    width: videoElement.videoWidth || canvasElement.width,
                    height: videoElement.videoHeight || canvasElement.height,
                    phases: { open: rombergFrames[1], closed: rombergFrames[2] }
                })
            });
            const result = await readJson(response);
            if (!response.ok || !result.ok) {
                throw new Error(result.error || 'No se pudo guardar la evaluación.');
            }
            if (!result.valid) {
                showRombergResult('warning', 'Hay que repetir la evaluación', [
                    'La cámara no vio bien a la persona en alguna fase (debe verse de la cabeza a los pies).',
                    describePhase('Ojos abiertos', result.open),
                    describePhase('Ojos cerrados', result.closed)
                ]);
                return;
            }
            showRombergResult('success', `Evaluación ${result.type.toLowerCase()} guardada`, [
                describePhase('Ojos abiertos', result.open),
                describePhase('Ojos cerrados', result.closed),
                'Recargando la página...'
            ]);
            window.setTimeout(() => window.location.assign(window.location.pathname), 2500);
        } catch (error) {
            showRombergResult('danger', 'No se guardó la evaluación', [error.message]);
        }
    }

    async function analizarConPython() {
        const now = performance.now();
        if (pythonAnalysisInFlight || now - lastPythonAnalysisAt < PYTHON_ANALYSIS_INTERVAL_MS) {
            return;
        }
        // Se espera a tener casi 1 s de fotogramas antes de la primera decisión.
        if (!frameBuffer.length || now - frameBuffer[0].t < WINDOW_MS * 0.8) {
            return;
        }
        const testType = getTestType();
        // Romberg: se envían los últimos 3 s de la fase (7 puntos por fotograma); si no, el último segundo.
        const phaseFrames = rombergFrames[currentPhase] || [];
        const frames = MODEL_TESTS.has(testType)
            ? frameBuffer.map((item) => item.lm)
            : phaseFrames.filter((f) => now - f.t <= ROMBERG_LIVE_MS);

        pythonAnalysisInFlight = true;
        lastPythonAnalysisAt = now;
        const sentAt = performance.now();
        try {
            const response = await fetch('/api/analizar-pose/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    testType,
                    side: getSide(),
                    // Si ya estaba en la postura, el servidor usa un umbral más tolerante (histéresis).
                    inPosture: postureReady,
                    width: videoElement.videoWidth || canvasElement.width,
                    height: videoElement.videoHeight || canvasElement.height,
                    frames
                })
            });
            const result = await readJson(response);
            const latency = performance.now() - sentAt;
            if (!response.ok || !result.ok) {
                throw new Error(result.error || 'El analizador no pudo procesar la pose.');
            }

            if (MODEL_TESTS.has(testType)) {
                handleModelResult(result, latency);
                return;
            }

            // Romberg en vivo: solo se muestra; el resultado se calcula al final con las dos fases.
            if (!result.valido) {
                setAnalysisStatus(result.message || 'Colóquese de cuerpo entero frente a la cámara', true);
                return;
            }
            if (metricSway) metricSway.textContent = `${result.amplitud_cm} cm`;
            if (metricSide) metricSide.textContent = result.lado || '--';
            if (metricAngle) metricAngle.textContent = `${Number(result.tronco_g).toFixed(1)}°`;
            setAnalysisStatus(result.message, false);
        } catch (error) {
            setAnalysisStatus(`Error del modelo: ${error.message}`, true);
            console.warn('No se pudo ejecutar el modelo Python:', error);
        } finally {
            pythonAnalysisInFlight = false;
        }
    }

    function handleModelResult(result, latency) {
        if (!result.valido) {
            setAnalysisStatus(result.mensaje || 'Colóquese frente a la cámara', true);
            return;
        }
        if (result.posicion) {
            console.debug('[Axon] posición', result.en_posicion, JSON.stringify(result.posicion));
        }
        if (!postureReady) {
            if (!result.en_posicion) {
                // Todavía no está en la postura: se indica cómo colocarse y el reloj no corre.
                consecutiveIncorrect += 1;
                setAnalysisStatus(`Para empezar: ${result.mensaje}`, true);
                if (consecutiveIncorrect >= SPEECH_PERSISTENCE) speak(result.mensaje);
                return;
            }
            postureReady = true;
            evaluationStartedAt = performance.now();
            resetModelStats(true);
            videoElement.dispatchEvent(new CustomEvent('axon:posture-ready'));
            speak('Posición correcta. Empezamos', true);
        }
        if (modelStats && workActive) {
            modelStats.windows += 1;
            modelStats.latencies.push(latency);
            if (result.incorrecto) {
                modelStats.incorrect += 1;
                if (result.error) {
                    modelStats.errors[result.error] = (modelStats.errors[result.error] || 0) + 1;
                }
            }
        }
        consecutiveIncorrect = result.incorrecto ? consecutiveIncorrect + 1 : 0;
        setAnalysisStatus(result.mensaje, result.incorrecto);
        if (metricAngle && result.medidas) {
            metricAngle.textContent = `${Number(result.medidas.tronco_lateral_g).toFixed(1)}°`;
        }
        if (consecutiveIncorrect >= SPEECH_PERSISTENCE) {
            speak(result.mensaje);
        }
        const summary = summarizeModelStats();
        latestAnalysis = {
            estabilidad: summary ? (100 - summary.incorrectPct).toFixed(1) : '0.0',
            desviacionCm: '0.00',
            alineacionOptima: !result.incorrecto,
            modelo: summary
        };
        videoElement.dispatchEvent(new CustomEvent('axon:pose-analysis', { detail: latestAnalysis }));
    }

    function setCameraBadge(active) {
        badgeCamera.textContent = active ? 'Camara activa' : 'Camara inactiva';
        badgeCamera.classList.add('neutral');
        badgeCamera.classList.toggle('badge-on', active);
    }

    function updateProgressUI(elapsedSeconds) {
        const progress = Math.min((elapsedSeconds / TEST_DURATION_SECONDS) * 100, 100);
        const remaining = Math.max(TEST_DURATION_SECONDS - Math.floor(elapsedSeconds), 0);
        const remainingText = `00:${String(remaining).padStart(2, '0')}`;

        if (progressBar) {
            progressBar.style.width = `${progress.toFixed(1)}%`;
        }
        if (timerLabel) {
            timerLabel.textContent = remainingText;
        }
        videoElement.dispatchEvent(new CustomEvent('axon:tick', {
            detail: { remaining, total: TEST_DURATION_SECONDS }
        }));
    }

    function updatePhaseUI() {
        const phaseName = currentPhase === 1 ? 'Ojos Abiertos' : 'Ojos Cerrados';
        if (phaseIndicator) {
            phaseIndicator.textContent = `Fase ${currentPhase} de ${TOTAL_PHASES}: ${phaseName}`;
        }
    }

    function showPhaseNotice(message) {
        if (!phaseNotice) {
            return;
        }
        phaseNotice.textContent = message;
        phaseNotice.classList.remove('d-none');
    }

    function resetProgressUI() {
        if (progressBar) {
            progressBar.style.width = '0%';
        }
        if (timerLabel) {
            timerLabel.textContent = DURATION_TEXT;
        }
        updatePhaseUI();
        if (phaseNotice) {
            phaseNotice.textContent = '';
            phaseNotice.classList.add('d-none');
        }
        btnStart.innerHTML = '<i class="fas fa-play me-2"></i> Comenzar evaluación';
    }

    function drawSkeleton(landmarks) {
        const customConnections = [
            [11, 12],
            [11, 23],
            [12, 24],
            [23, 24],
            [23, 25],
            [24, 26],
            [25, 27],
            [26, 28],
            [27, 31],
            [28, 32]
        ];

        customConnections.forEach(([start, end]) => {
            window.drawConnectors(ctx, landmarks, [[start, end]], {
                color: '#38bdf8',
                lineWidth: 3
            });
        });

        window.drawLandmarks(ctx, landmarks, {
            color: '#f59e0b',
            fillColor: '#fef3c7',
            radius: 4
        });
    }

    // Cualquier error al dibujar o analizar un fotograma se registra, pero no detiene la cámara.
    function onPoseResults(results) {
        try {
            onPoseResultsInner(results);
        } catch (error) {
            console.warn('Error al procesar el fotograma:', error);
            try { ctx.restore(); } catch (e) { /* nada */ }
        }
    }

    function onPoseResultsInner(results) {
        ctx.save();
        ctx.clearRect(0, 0, canvasElement.width, canvasElement.height);
        ctx.drawImage(results.image, 0, 0, canvasElement.width, canvasElement.height);

        if (results.poseLandmarks) {
            if (results.poseLandmarks.length < 33) {
                setAnalysisStatus('No se detectó el cuerpo completo.', true);
                ctx.restore();
                return;
            }
            drawSkeleton(results.poseLandmarks);
            const frameTime = performance.now();
            frameBuffer.push({
                t: frameTime,
                lm: results.poseLandmarks.map((p) => [
                    Number(p.x.toFixed(5)), Number(p.y.toFixed(5)), Number((p.z || 0).toFixed(5)),
                    Number((typeof p.visibility === 'number' ? p.visibility : 1).toFixed(3))
                ])
            });
            while (frameBuffer.length && frameTime - frameBuffer[0].t > WINDOW_MS) {
                frameBuffer.shift();
            }
            if (modelStats && workActive) {
                modelStats.frames += 1;
            }
            if (MODEL_TESTS.has(getTestType())) {
                analizarConPython();
                ctx.restore();
                return;
            }
            // Romberg: se guardan los 7 puntos de cada fotograma de la fase en curso.
            if (workActive && rombergFrames[currentPhase]) {
                rombergFrames[currentPhase].push({
                    t: frameTime,
                    p: ROMBERG_POINTS.map((i) => {
                        const q = results.poseLandmarks[i];
                        return [Number(q.x.toFixed(4)), Number(q.y.toFixed(4)),
                            Number((typeof q.visibility === 'number' ? q.visibility : 1).toFixed(2))];
                    })
                });
            }
            analizarConPython();
        }

        ctx.restore();
    }

    async function processFrameLoop() {
        if (!isRunning || !workActive || !poseRef || frameInFlight) {
            return;
        }

        frameInFlight = true;
        try {
            // Si MediaPipe no responde en 3 s, se suelta el fotograma para que la cámara no quede congelada.
            await Promise.race([
                poseRef.send({ image: videoElement }),
                new Promise((resolve) => window.setTimeout(resolve, 3000))
            ]);
        } catch (error) {
            // Antes aquí se salía del ciclo y la imagen quedaba congelada para siempre.
            if (isRunning) {
                console.warn('No se pudo procesar un fotograma:', error);
            }
        } finally {
            frameInFlight = false;
        }

        if (!isRunning || !workActive) {
            return;
        }

        if (!postureReady) {
            // Esperando la postura: el reloj se queda en la duración completa.
            updateProgressUI(0);
            animationRef = window.requestAnimationFrame(processFrameLoop);
            return;
        }
        const elapsedSeconds = (performance.now() - evaluationStartedAt) / 1000;
        updateProgressUI(elapsedSeconds);

        if (elapsedSeconds >= TEST_DURATION_SECONDS) {
            if (isRoutine) {
                pauseRoutineWork();
                resetProgressUI();
                const detail = Object.assign({}, latestAnalysis || {}, { modelo: summarizeModelStats() });
                videoElement.dispatchEvent(new CustomEvent('axon:work-complete', { detail }));
            } else if (currentPhase === 1) {
                completeOpenEyesPhase();
            } else {
                finishRomberg();
            }
            return;
        }

        animationRef = window.requestAnimationFrame(processFrameLoop);
    }

    function completeOpenEyesPhase() {
        workActive = false;
        if (animationRef) {
            window.cancelAnimationFrame(animationRef);
            animationRef = null;
        }
        currentPhase = 2;
        updatePhaseUI();
        updateProgressUI(0);
        showPhaseNotice('Fase 1 completada. Prepárese para cerrar los ojos.');
        btnStart.disabled = false;
        btnStart.innerHTML = '<i class="fas fa-play me-2"></i> Iniciar fase 2';
        setAnalysisStatus('Listo para iniciar ojos cerrados.', false);
    }

    // Fin de la fase 2: se apaga la cámara y se envían las dos fases para calcular el resultado.
    async function finishRomberg() {
        await stopEvaluation(true);
        await enviarRomberg();
    }

    function startClosedEyesPhase() {
        currentPhase = 2;
        workActive = true;
        evaluationStartedAt = performance.now();
        latestAnalysis = null;
        rombergFrames[2] = [];
        lastPythonAnalysisAt = 0;
        resetModelStats();
        armPostureGate();
        updatePhaseUI();
        if (phaseNotice) {
            phaseNotice.textContent = 'Fase 2 iniciada. Mantenga los ojos cerrados durante 30 segundos.';
        }
        setAnalysisStatus('Buscando cuerpo...', false);
        btnStart.disabled = true;
        processFrameLoop();
    }

    async function startEvaluation() {
        if (isRunning || startInFlight) {
            if (!isRoutine && isRunning && currentPhase === 2 && !workActive) {
                startClosedEyesPhase();
            }
            return;
        }

        if (!window.Pose || !window.drawLandmarks || !window.drawConnectors) {
            alert('No se cargaron las librerias de MediaPipe Pose.');
            return;
        }

        startInFlight = true;
        try {
            streamRef = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640, max: 1280 },
                    height: { ideal: 480, max: 720 },
                    facingMode: 'user'
                },
                audio: false
            });

            videoElement.srcObject = streamRef;
            await videoElement.play();

            canvasElement.width = videoElement.videoWidth || 1280;
            canvasElement.height = videoElement.videoHeight || 720;

            poseRef = new window.Pose({
                locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${file}`
            });

            poseRef.setOptions({
                modelComplexity: 0,
                smoothLandmarks: true,
                enableSegmentation: false,
                minDetectionConfidence: 0.6,
                minTrackingConfidence: 0.6
            });

            poseRef.onResults(onPoseResults);

            isRunning = true;
            workActive = true;
            currentPhase = 1;
            evaluationStartedAt = performance.now();
            latestAnalysis = null;
            rombergFrames[1] = [];
            rombergFrames[2] = [];
            lastPythonAnalysisAt = 0;
            lastAlertAt = 0;
            resetModelStats();
            armPostureGate();
            setCameraBadge(true);
            setAnalysisStatus('Buscando cuerpo...', false);
            btnStart.disabled = true;
            btnStop.disabled = false;
            updatePhaseUI();
            if (phaseNotice) {
                phaseNotice.textContent = 'Fase 1 iniciada. Mantenga los ojos abiertos durante 30 segundos.';
                phaseNotice.classList.remove('d-none');
            }

            processFrameLoop();
        } catch (error) {
            console.error('Error al iniciar evaluacion:', error);
            alert('No fue posible acceder a la camara. Verifique permisos del navegador.');
            videoElement.dispatchEvent(new CustomEvent('axon:start-failed'));
            stopEvaluation();
        } finally {
            startInFlight = false;
        }
    }

    // completed = true solo cuando terminan las dos fases del Romberg; con "Detener" no se guarda nada.
    async function stopEvaluation(completed) {
        const wasRomberg = !isRoutine && isRunning;
        isRunning = false;
        workActive = false;

        if (animationRef) {
            window.cancelAnimationFrame(animationRef);
            animationRef = null;
        }

        if (streamRef) {
            streamRef.getTracks().forEach((track) => track.stop());
            streamRef = null;
        }

        if (poseRef && typeof poseRef.close === 'function') {
            try {
                await poseRef.close();
            } catch (error) {
                console.warn('No se pudo cerrar el modelo de pose:', error);
            } finally {
                poseRef = null;
            }
        }

        if (videoElement.srcObject) {
            videoElement.srcObject = null;
        }

        setCameraBadge(false);
        badgeAlignment.textContent = 'En espera';
        badgeAlignment.classList.remove('warning');
        badgeAlignment.classList.add('success');
        if (!isRoutine) {
            btnStart.disabled = false;
        }
        btnStop.disabled = true;
        currentPhase = 1;
        resetProgressUI();
        if (wasRomberg && completed !== true) {
            showRombergResult('warning', 'Evaluación detenida', ['No se guardó. Puede volver a empezar.']);
        }
    }

    function pauseRoutineWork() {
        if (!isRunning) {
            return;
        }
        workActive = false;
        if (animationRef) {
            window.cancelAnimationFrame(animationRef);
            animationRef = null;
        }
    }

    function resumeRoutineWork() {
        if (!isRunning || workActive) {
            return;
        }
        workActive = true;
        evaluationStartedAt = performance.now();
        latestAnalysis = null;
        lastPythonAnalysisAt = 0;
        resetModelStats();
        armPostureGate();
        setAnalysisStatus('Buscando cuerpo...', false);
        processFrameLoop();
    }

    videoElement.addEventListener('axon:pause-work', pauseRoutineWork);
    videoElement.addEventListener('axon:resume-work', resumeRoutineWork);
    videoElement.addEventListener('axon:end-routine', () => stopEvaluation(false));
    videoElement.addEventListener('axon:start-failed', () => {
        isRunning = false;
        workActive = false;
    });
    videoElement.addEventListener('axon:start-work', startEvaluation);
    if (!isRoutine) {
        btnStart.addEventListener('click', startEvaluation);
    }
    btnStop.addEventListener('click', () => stopEvaluation(false));
})();