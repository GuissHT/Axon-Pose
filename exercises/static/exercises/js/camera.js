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
    const metricStability = document.getElementById('metricStability');
    const metricDeviation = document.getElementById('metricDeviation');
    const badgeCamera = document.getElementById('badgeCamera');
    const badgeAlignment = document.getElementById('badgeAlignment');
    const testTypeSelect = document.getElementById('testTypeSelect');

    const TEST_DURATION_SECONDS = 30;
    let streamRef = null;
    let poseRef = null;
    let animationRef = null;
    let isRunning = false;
    let evaluationStartedAt = 0;
    let latestAnalysis = null;
    const analysisWindow = [];
    const MAX_WINDOW = 12;

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
            }
        };

        return configs[testType] || configs['Marcha Tandem'];
    }

    function getCsrfToken() {
        const cookies = document.cookie ? document.cookie.split(';') : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith('csrftoken=')) {
                return decodeURIComponent(trimmed.substring('csrftoken='.length));
            }
        }
        return '';
    }

    async function guardarSesionEnBackend() {
        if (!latestAnalysis) {
            return;
        }

        const payload = {
            testType: testTypeSelect ? testTypeSelect.value : 'Diagnostico general',
            stability: latestAnalysis.estabilidad,
            deviationCm: latestAnalysis.desviacionCm,
            alignment: latestAnalysis.alineacionOptima ? 'Optima' : 'Requiere ajuste',
            qualityScore: latestAnalysis.qualityScore
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

    function setCameraBadge(active) {
        badgeCamera.textContent = active ? 'Camara activa' : 'Camara inactiva';
        badgeCamera.classList.add('neutral');
        badgeCamera.classList.toggle('badge-on', active);
    }

    function updateProgressUI(elapsedSeconds) {
        const progress = Math.min((elapsedSeconds / TEST_DURATION_SECONDS) * 100, 100);
        const remaining = Math.max(TEST_DURATION_SECONDS - Math.floor(elapsedSeconds), 0);
        const remainingText = `00:${String(remaining).padStart(2, '0')}`;

        progressBar.style.width = `${progress.toFixed(1)}%`;
        timerLabel.textContent = remainingText;
    }

    function resetProgressUI() {
        progressBar.style.width = '0%';
        timerLabel.textContent = '00:30';
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

        const testType = testTypeSelect ? testTypeSelect.value : 'Marcha Tandem';
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

            metricStability.textContent = `${analisis.estabilidad}%`;
            metricDeviation.textContent = `${analisis.desviacionCm} cm`;

            badgeAlignment.textContent = analisis.alineacionOptima ? 'Alineacion optima' : 'Ajustar alineacion';
            badgeAlignment.classList.toggle('success', analisis.alineacionOptima);
            badgeAlignment.classList.toggle('warning', !analisis.alineacionOptima);
        }

        ctx.restore();
    }

    async function processFrameLoop() {
        if (!isRunning || !poseRef) {
            return;
        }

        await poseRef.send({ image: videoElement });

        const elapsedSeconds = (performance.now() - evaluationStartedAt) / 1000;
        updateProgressUI(elapsedSeconds);

        if (elapsedSeconds >= TEST_DURATION_SECONDS) {
            stopEvaluation();
            return;
        }

        animationRef = window.requestAnimationFrame(processFrameLoop);
    }

    async function startEvaluation() {
        if (isRunning) {
            return;
        }

        if (!window.Pose || !window.drawLandmarks || !window.drawConnectors) {
            alert('No se cargaron las librerias de MediaPipe Pose.');
            return;
        }

        try {
            streamRef = await navigator.mediaDevices.getUserMedia({
                video: { width: 1280, height: 720 },
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
                modelComplexity: 1,
                smoothLandmarks: true,
                enableSegmentation: false,
                minDetectionConfidence: 0.6,
                minTrackingConfidence: 0.6
            });

            poseRef.onResults(onPoseResults);

            isRunning = true;
            evaluationStartedAt = performance.now();
            latestAnalysis = null;
            analysisWindow.length = 0;
            setCameraBadge(true);
            btnStart.disabled = true;
            btnStop.disabled = false;

            processFrameLoop();
        } catch (error) {
            console.error('Error al iniciar evaluacion:', error);
            alert('No fue posible acceder a la camara. Verifique permisos del navegador.');
            stopEvaluation();
        }
    }

    async function stopEvaluation() {
        isRunning = false;

        if (animationRef) {
            window.cancelAnimationFrame(animationRef);
            animationRef = null;
        }

        if (streamRef) {
            streamRef.getTracks().forEach((track) => track.stop());
            streamRef = null;
        }

        if (videoElement.srcObject) {
            videoElement.srcObject = null;
        }

        setCameraBadge(false);
        badgeAlignment.textContent = 'Alineacion en espera';
        badgeAlignment.classList.remove('warning');
        badgeAlignment.classList.add('success');
        btnStart.disabled = false;
        btnStop.disabled = true;
        resetProgressUI();

        await guardarSesionEnBackend();
    }

    btnStart.addEventListener('click', startEvaluation);
    btnStop.addEventListener('click', stopEvaluation);
})();