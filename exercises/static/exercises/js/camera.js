/*
   Este archivo controla la evaluacion visual en diagnostico:
   1) Enciende/apaga camara
   2) Ejecuta MediaPipe Pose
   3) Dibuja esqueleto en canvas
   4) Calcula estabilidad y desviacion lateral
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
    const metricStability = document.getElementById('metricStability');
    const metricDeviation = document.getElementById('metricDeviation');
    const metricAngle = document.getElementById('metricAngle');
    const badgeCamera = document.getElementById('badgeCamera');
    const badgeAlignment = document.getElementById('badgeAlignment');
    const testType = 'Equilibrio Estatico';
    const isRoutine = document.body.dataset.routine === 'true';
    const evaluationType = document.body.dataset.evaluationType || 'INICIAL';

    const TEST_DURATION_SECONDS = 30;
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
    const analysisWindow = [];
    const MAX_WINDOW = 12;
    const PYTHON_ANALYSIS_INTERVAL_MS = 500;
    const ALERT_INTERVAL_MS = 1500;

    function getExerciseConfig(testType) {
        const configs = {
            'Equilibrio Estatico': {
                verticalTolerance: 0.055,
                trunkTolerance: 0.05,
                stabilityThreshold: 84,
                swayWeight: 0.2
            },
            'Soporte Monopodal': {
                verticalTolerance: 0.075,
                trunkTolerance: 0.07,
                stabilityThreshold: 74,
                swayWeight: 0.32
            },
            'Marcha Tandem': {
                verticalTolerance: 0.068,
                trunkTolerance: 0.06,
                stabilityThreshold: 78,
                swayWeight: 0.28
            },
            'Postura del Arbol': {
                verticalTolerance: 0.06,
                trunkTolerance: 0.05,
                stabilityThreshold: 80,
                swayWeight: 0.2
            }
        };

        return configs[testType] || configs['Marcha Tandem'];
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

    function setAnalysisStatus(message, isError) {
        badgeAlignment.textContent = message;
        badgeAlignment.classList.toggle('warning', Boolean(isError));
        badgeAlignment.classList.toggle('success', !isError);
    }

    async function guardarSesionEnBackend() {
        if (isRoutine) {
            return;
        }
        if (!latestAnalysis) {
            return;
        }

        const payload = {
            testType,
            stability: latestAnalysis.estabilidad,
            deviationCm: latestAnalysis.desviacionCm,
            alignment: latestAnalysis.alineacionOptima ? 'Optima' : 'Requiere ajuste',
            qualityScore: latestAnalysis.qualityScore,
            evaluationType: evaluationType,
            angleDeg: metricAngle
                ? Number(metricAngle.textContent.replace('°', '')) || 0
                : 0
        };

        try {
            await fetch('/api/registrar-metricas/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(payload)
            });
        } catch (error) {
            console.warn('No se pudieron guardar metricas de sesion:', error);
        }
    }

    async function analizarConPython(landmarks) {
        const now = performance.now();
        if (pythonAnalysisInFlight || now - lastPythonAnalysisAt < PYTHON_ANALYSIS_INTERVAL_MS) {
            return;
        }

        pythonAnalysisInFlight = true;
        lastPythonAnalysisAt = now;
        try {
            const response = await fetch('/api/analizar-pose/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    testType,
                    landmarks
                })
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || 'El analizador no pudo procesar la pose.');
            }

            latestAnalysis = {
                estabilidad: Number(result.stability).toFixed(1),
                desviacionCm: Number(result.deviation_cm).toFixed(2),
                alineacionOptima: result.alignment === 'Optima',
                qualityScore: latestAnalysis ? latestAnalysis.qualityScore : '0.0'
            };
            videoElement.dispatchEvent(new CustomEvent('axon:pose-analysis', {
                detail: latestAnalysis
            }));
            const angleValues = Object.values(result.angles || {});
            if (metricAngle) {
                metricAngle.textContent = angleValues.length
                    ? `${Number(angleValues[0]).toFixed(1)}°`
                    : '--';
            }
            if (metricStability) {
                metricStability.textContent = `${latestAnalysis.estabilidad}%`;
            }
            if (metricDeviation) {
                metricDeviation.textContent = `${latestAnalysis.desviacionCm} cm`;
            }
            badgeAlignment.textContent = result.message;
            badgeAlignment.classList.toggle('success', !result.alert);
            badgeAlignment.classList.toggle('warning', result.alert);
            if (result.alert) {
                playAlert();
            }
        } catch (error) {
            setAnalysisStatus(`Error del modelo: ${error.message}`, true);
            console.warn('No se pudo ejecutar el modelo Python:', error);
        } finally {
            pythonAnalysisInFlight = false;
        }
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
            timerLabel.textContent = '00:30';
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

    // Funcion preparada para usar landmarks y producir metricas de verticalidad.
    function analizarEquilibrio(landmarks) {
        const leftShoulder = landmarks[11];
        const rightShoulder = landmarks[12];
        const leftHip = landmarks[23];
        const rightHip = landmarks[24];
        const leftAnkle = landmarks[27];
        const rightAnkle = landmarks[28];

        const visibilityValues = [
            leftShoulder.visibility,
            rightShoulder.visibility,
            leftHip.visibility,
            rightHip.visibility,
            leftAnkle.visibility,
            rightAnkle.visibility
        ].map((value) => (typeof value === 'number' ? value : 1));

        const minVisibility = Math.min(...visibilityValues);
        if (minVisibility < 0.45) {
            return null;
        }

        const centerShoulderX = (leftShoulder.x + rightShoulder.x) / 2;
        const centerHipX = (leftHip.x + rightHip.x) / 2;
        const centerAnkleX = (leftAnkle.x + rightAnkle.x) / 2;
        const ankleDistance = Math.abs(leftAnkle.x - rightAnkle.x);

        const cfg = getExerciseConfig(testType);

        const verticalError = Math.abs(centerShoulderX - centerAnkleX);
        const trunkError = Math.abs(centerShoulderX - centerHipX);
        const verticalNorm = Math.min(verticalError / cfg.verticalTolerance, 1);
        const trunkNorm = Math.min(trunkError / cfg.trunkTolerance, 1);
        const swayNorm = Math.min(Math.abs(ankleDistance - 0.16) / 0.16, 1);

        const combinedNorm = (verticalNorm * 0.45) + (trunkNorm * 0.35) + (swayNorm * cfg.swayWeight);

        const rawStability = Math.max(0, 100 - (combinedNorm * 100));
        const rawDeviationCm = (verticalError + trunkError) * 100 * 0.22;

        analysisWindow.push({
            stability: rawStability,
            deviationCm: rawDeviationCm,
        });
        if (analysisWindow.length > MAX_WINDOW) {
            analysisWindow.shift();
        }

        const smoothedStability = analysisWindow.reduce((acc, item) => acc + item.stability, 0) / analysisWindow.length;
        const smoothedDeviation = analysisWindow.reduce((acc, item) => acc + item.deviationCm, 0) / analysisWindow.length;
        const qualityScore = Math.max(0, Math.min(100, minVisibility * 100));

        return {
            estabilidad: smoothedStability.toFixed(1),
            desviacionCm: smoothedDeviation.toFixed(2),
            alineacionOptima: smoothedStability >= cfg.stabilityThreshold,
            qualityScore: qualityScore.toFixed(1)
        };
    }

    function onPoseResults(results) {
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
            const analisis = analizarEquilibrio(results.poseLandmarks);
            if (!analisis) {
                badgeAlignment.textContent = 'Ajustar posicion frente a camara';
                badgeAlignment.classList.remove('success');
                badgeAlignment.classList.add('warning');
                ctx.restore();
                return;
            }
            latestAnalysis = analisis;
            videoElement.dispatchEvent(new CustomEvent('axon:pose-analysis', {
                detail: analisis
            }));

            if (metricStability) {
                metricStability.textContent = `${analisis.estabilidad}%`;
            }
            if (metricDeviation) {
                metricDeviation.textContent = `${analisis.desviacionCm} cm`;
            }

            badgeAlignment.textContent = analisis.alineacionOptima ? 'Alineacion optima' : 'Ajustar alineacion';
            badgeAlignment.classList.toggle('success', analisis.alineacionOptima);
            badgeAlignment.classList.toggle('warning', !analisis.alineacionOptima);
            setAnalysisStatus('Modelo activo: analizando postura', false);
            if (!isRoutine) {
                analizarConPython(results.poseLandmarks);
            }
        }

        ctx.restore();
    }

    async function processFrameLoop() {
        if (!isRunning || !workActive || !poseRef || frameInFlight) {
            return;
        }

        frameInFlight = true;
        try {
            await poseRef.send({ image: videoElement });
        } catch (error) {
            if (isRunning) {
                console.warn('No se pudo procesar un fotograma:', error);
            }
            return;
        } finally {
            frameInFlight = false;
        }

        if (!isRunning || !workActive) {
            return;
        }

        const elapsedSeconds = (performance.now() - evaluationStartedAt) / 1000;
        updateProgressUI(elapsedSeconds);

        if (elapsedSeconds >= TEST_DURATION_SECONDS) {
            if (isRoutine) {
                pauseRoutineWork();
                resetProgressUI();
                videoElement.dispatchEvent(new CustomEvent('axon:work-complete', {
                    detail: latestAnalysis
                }));
            } else if (currentPhase === 1) {
                completeOpenEyesPhase();
            } else {
                stopEvaluation();
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

    function startClosedEyesPhase() {
        currentPhase = 2;
        workActive = true;
        evaluationStartedAt = performance.now();
        latestAnalysis = null;
        analysisWindow.length = 0;
        lastPythonAnalysisAt = 0;
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
            analysisWindow.length = 0;
            lastPythonAnalysisAt = 0;
            lastAlertAt = 0;
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

    async function stopEvaluation() {
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
        badgeAlignment.textContent = 'Alineacion en espera';
        badgeAlignment.classList.remove('warning');
        badgeAlignment.classList.add('success');
        if (!isRoutine) {
            btnStart.disabled = false;
        }
        btnStop.disabled = true;
        currentPhase = 1;
        resetProgressUI();

        if (!isRoutine) {
            await guardarSesionEnBackend();
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
        analysisWindow.length = 0;
        lastPythonAnalysisAt = 0;
        setAnalysisStatus('Buscando cuerpo...', false);
        processFrameLoop();
    }

    videoElement.addEventListener('axon:pause-work', pauseRoutineWork);
    videoElement.addEventListener('axon:resume-work', resumeRoutineWork);
    videoElement.addEventListener('axon:end-routine', stopEvaluation);
    videoElement.addEventListener('axon:start-failed', () => {
        isRunning = false;
        workActive = false;
    });
    videoElement.addEventListener('axon:start-work', startEvaluation);
    if (!isRoutine) {
        btnStart.addEventListener('click', startEvaluation);
    }
    btnStop.addEventListener('click', stopEvaluation);
})();