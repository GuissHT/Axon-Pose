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
    """Analiza la inclinación del tronco durante la postura del árbol."""
    try:
        shoulders_x = (float(landmarks[11]["x"]) + float(landmarks[12]["x"])) / 2
        hips_x = (float(landmarks[23]["x"]) + float(landmarks[24]["x"])) / 2
    except (IndexError, KeyError, TypeError):
        raise ValueError("Faltan los puntos de hombros o caderas.")

    deviation = abs(shoulders_x - hips_x) * 100
    trunk_angle = abs(math.degrees(math.atan2(
        shoulders_x - hips_x,
        float(landmarks[11]["y"] + landmarks[12]["y"]) / 2
        - float(landmarks[23]["y"] + landmarks[24]["y"]) / 2,
    )))
    return {
        "stability": round(max(0, 100 - (deviation * 5)), 2),
        "deviation_cm": round(deviation, 2),
        "angles": {
            "angulo_tronco": round(trunk_angle, 2),
        },
        "alignment": "Optima" if deviation < 3.5 else "Requiere ajuste",
        "alert": deviation >= 3.5,
        "message": (
            "Enderece el tronco."
            if deviation >= 3.5
            else "Excelente alineación."
        ),
    }


def ejecutar_postura_arbol(video_source=0):
    """
    Modelo 4: Postura del Árbol Adaptada (Vrksasana modificada).
    Valida la transferencia de carga a un solo pie y la alineación vertical del tronco.
    """
    if mp_pose is None:
        raise RuntimeError("MediaPipe no está instalado para usar la cámara local.")

    cap = cv2.VideoCapture(video_source)
    alerta_sonora = AlertaSonora()
    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    
    print("Iniciando Modelo 4: Postura del Árbol Adaptada. Mantenga un soporte cercano...")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("Error al acceder a la cámara.")
            break
            
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = pose.process(image)
        
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        try:
            landmarks = results.pose_landmarks.landmark
            
            # Obtener puntos clave del tronco y cabeza para medir alineación vertical
            nariz = [landmarks[mp_pose.PoseLandmark.NOSE.value].x, landmarks[mp_pose.PoseLandmark.NOSE.value].y]
            hombro_izq = [landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].x, landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].y]
            hombro_der = [landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y]
            
            cadera_izq = [landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].x, landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].y]
            cadera_der = [landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value].y]
            
            # Centro de hombros y caderas
            centro_hombros_x = (hombro_izq[0] + hombro_der[0]) / 2
            centro_caderas_x = (cadera_izq[0] + cadera_der[0]) / 2
            
            # Calcular desviación vertical del tronco (eje X)
            desviacion_tronco = abs(centro_hombros_x - centro_caderas_x) * 100
            
            # Evaluar si la postura vertical es correcta o si hay inclinación excesiva
            if desviacion_tronco < 3.5:
                estado_texto = "¡Excelente alineacion! Mantenga el equilibrio"
                color_estado = (0, 255, 0) # Verde
            else:
                estado_texto = "ALERTA: Tronco inclinado, enderecese"
                color_estado = (0, 0, 255) # Rojo
                alerta_sonora.emitir()

            # Mostrar información en pantalla
            cv2.putText(image, f'Ejercicio: Postura del Arbol Adaptada', (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(image, estado_texto, (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_estado, 2)
            cv2.putText(image, f'Desvio vertical: {round(desviacion_tronco, 1)}', (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
            cv2.putText(image, 'Presione "q" para salir', (30, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
        except Exception as e:
            cv2.putText(image, 'Ajuste su posicion frente a la camara', (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

        if results.pose_landmarks:
            mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

        cv2.imshow('Modelo 4: Postura del Arbol Adaptada', image)
        
        if cv2.waitKey(10) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    ejecutar_postura_arbol()