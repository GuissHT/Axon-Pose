import cv2
import math
import numpy as np
from .alertas_sonoras import AlertaSonora

try:
    import mediapipe as mp
except ImportError:
    mp = None

mp_pose = mp.solutions.pose if mp else None
mp_drawing = mp.solutions.drawing_utils if mp else None


def analizar(landmarks):
    """Analiza la alineación del tronco durante la marcha tándem."""
    try:
        shoulder_width = float(landmarks[11]["x"]) - float(landmarks[12]["x"])
        hip_width = float(landmarks[23]["x"]) - float(landmarks[24]["x"])
    except (IndexError, KeyError, TypeError):
        raise ValueError("Faltan los puntos de hombros o caderas.")

    deviation = abs(shoulder_width - hip_width) * 100
    shoulder_angle = abs(math.degrees(math.atan2(
        float(landmarks[11]["y"]) - float(landmarks[12]["y"]),
        shoulder_width,
    )))
    return {
        "stability": round(max(0, 100 - (deviation * 4)), 2),
        "deviation_cm": round(deviation, 2),
        "angles": {
            "angulo_hombros": round(shoulder_angle, 2),
        },
        "alignment": "Optima" if deviation <= 5 else "Requiere ajuste",
        "alert": deviation > 5,
        "message": (
            "Corrija el equilibrio lateral."
            if deviation > 5
            else "Postura estable en tándem."
        ),
    }


def ejecutar_marcha_tandem(video_source=0):
    """
    Modelo 2: Marcha Tándem (Talón-Punta).
    Monitorea la alineación horizontal de los hombros y caderas para detectar 
    desequilibrios laterales durante la caminata en línea recta.
    """
    if mp_pose is None:
        raise RuntimeError("MediaPipe no está instalado para usar la cámara local.")

    cap = cv2.VideoCapture(video_source)
    alerta_sonora = AlertaSonora()
    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    
    print("Iniciando Modelo 2: Marcha Tándem. Colóquese de perfil o frente a la cámara...")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("Error al acceder a la cámara.")
            break
            
        # Convertir imagen a RGB para MediaPipe
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = pose.process(image)
        
        # Volver a BGR para OpenCV
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        try:
            landmarks = results.pose_landmarks.landmark
            
            # Obtener puntos de los hombros y caderas para medir estabilidad lateral
            hombro_izq = [landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].x, landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].y]
            hombro_der = [landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y]
            
            cadera_izq = [landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].x, landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].y]
            cadera_der = [landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value].y]
            
            # Calcular la diferencia en el eje X (inclinación lateral del tronco)
            desequilibrio_lateral = abs((hombro_izq[0] - hombro_der[0]) - (cadera_izq[0] - cadera_der[0])) * 100
            
            # Definir umbral de alerta (si el desvío lateral supera los 5 puntos porcentuales)
            if desequilibrio_lateral > 5.0:
                estado_texto = "ALERTA: Desequilibrio lateral detectado"
                color_alerta = (0, 0, 255) # Rojo
                alerta_sonora.anunciar_estado("incorrecta")
                estado_actual = "incorrecta"
            else:
                estado_texto = "Postura Estable en Tandem"
                color_alerta = (0, 255, 0) # Verde
                estado_actual = "correcta"

            if (
                estado_actual == "correcta"
                and alerta_sonora.ultimo_estado == "incorrecta"
            ):
                alerta_sonora.anunciar_estado("corregida")
                
            # Mostrar información en pantalla
            cv2.putText(image, f'Ejercicio: Marcha Tandem', (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(image, estado_texto, (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_alerta, 2)
            cv2.putText(image, f'Desvio: {round(desequilibrio_lateral, 1)}', (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            
        except Exception as e:
            # En caso de que no detecte el cuerpo completo en el encuadre
            cv2.putText(image, 'Ajuste su posicion frente a la camara', (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        # Dibujar malla esquelética
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

        cv2.imshow('Modelo 2: Marcha Tandem (Talon-Punta)', image)
        
        # Presionar 'q' para salir
        if cv2.waitKey(10) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    ejecutar_marcha_tandem()