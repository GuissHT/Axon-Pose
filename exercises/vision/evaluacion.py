import cv2
import math
import numpy as np
from .alertas_sonoras import AlertaSonora

try:
    import mediapipe as mp
except ImportError:
    mp = None

# Inicialización segura de MediaPipe Pose
mp_pose = mp.solutions.pose if mp else None
mp_drawing = mp.solutions.drawing_utils if mp else None


def analizar(landmarks):
    """Analiza una pose enviada por el navegador para la evaluación inicial."""
    try:
        left = landmarks[11]
        right = landmarks[12]
    except (IndexError, KeyError, TypeError):
        raise ValueError("Faltan los puntos de los hombros.")

    desnivel = abs(float(left["y"]) - float(right["y"])) * 100
    hombros_angle = abs(math.degrees(math.atan2(
        float(left["y"]) - float(right["y"]),
        float(left["x"]) - float(right["x"]),
    )))
    return {
        "stability": round(max(0, 100 - (desnivel * 10)), 2),
        "deviation_cm": round(desnivel, 2),
        "angles": {
            "angulo_hombros": round(hombros_angle, 2),
        },
        "alignment": "Optima" if desnivel < 3 else "Requiere ajuste",
        "alert": desnivel >= 3,
        "message": "Alinee los hombros." if desnivel >= 3 else "Postura correcta.",
    }


def evaluar_postura_estatica(video_source=0):
    """
    Modelo 1: Evalúa la alineación vertical y simetría corporal (Hombros y Tronco).
    Retorna métricas de desviación para guardar en la base de datos como línea base.
    """
    if mp_pose is None:
        raise RuntimeError("MediaPipe no está instalado para usar la cámara local.")

    cap = cv2.VideoCapture(video_source)
    alerta_sonora = AlertaSonora()
    
    # Instanciamos el modelo Pose de MediaPipe
    with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
        
        resultados_sesion = {"hombro_desnivel": 0, "inclinacion_tronco": 0, "estado": "Evaluando..."}
        
        print("Iniciando evaluación postural inicial. Manténgase de pie frente a la cámara...")

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                print("No se pudo acceder a la cámara.")
                break
                
            # Convertir la imagen a RGB
            image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image.flags.writeable = False
            results = pose.process(image)
            
            # Volver a convertir a BGR para OpenCV
            image.flags.writeable = True
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            
            if results.pose_landmarks:
                landmarks = results.pose_landmarks.landmark
                
                # Coordenadas de hombros (Izquierdo y Derecho)
                hombro_izq = [
                    landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].x, 
                    landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].y
                ]
                hombro_der = [
                    landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x, 
                    landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y
                ]
                
                # Calcular desnivel de hombros (Diferencia en el eje Y)
                desnivel_hombros = abs(hombro_izq[1] - hombro_der[1]) * 100
                resultados_sesion["hombro_desnivel"] = round(desnivel_hombros, 2)
                
                # Visualización en pantalla
                color = (0, 255, 0) if desnivel_hombros < 3.0 else (0, 0, 255)
                if desnivel_hombros >= 3.0:
                    alerta_sonora.emitir()
                cv2.putText(image, f'Desnivel Hombros: {round(desnivel_hombros, 1)}%', 
                            (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                cv2.putText(image, 'Presione "ESC" para guardar evaluacion', 
                            (30, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                
                # Dibujar las malla corporal de guía
                mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

            cv2.imshow('Modelo 1: Evaluacion Postural Inicial', image)
            
            # Salir con la tecla ESC (código 27)
            if cv2.waitKey(10) & 0xFF == 27:
                break

    cap.release()
    cv2.destroyAllWindows()
    return resultados_sesion

if __name__ == "__main__":
    evaluar_postura_estatica()