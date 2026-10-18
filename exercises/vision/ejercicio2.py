import cv2
import numpy as np
from .alertas_sonoras import AlertaSonora

try:
    import mediapipe as mp
except ImportError:
    mp = None

mp_pose = mp.solutions.pose if mp else None
mp_drawing = mp.solutions.drawing_utils if mp else None


def analizar(landmarks):
    """Analiza el apoyo unipodal a partir de la altura de los tobillos."""
    try:
        left_ankle = landmarks[27]
        right_ankle = landmarks[28]
        left_knee = landmarks[25]
        right_knee = landmarks[26]
    except (IndexError, KeyError, TypeError):
        raise ValueError("Faltan los puntos de tobillos o rodillas.")

    height_difference = float(left_ankle["y"]) - float(right_ankle["y"])
    supported = abs(height_difference) >= 0.05
    if not supported:
        return {
            "stability": 0,
            "deviation_cm": round(abs(height_difference) * 100, 2),
            "angles": {},
            "alignment": "Requiere ajuste",
            "alert": True,
            "message": "Eleve una pierna para iniciar el apoyo unipodal.",
        }

    knee = left_knee if height_difference > 0 else right_knee
    ankle = left_ankle if height_difference > 0 else right_ankle
    deviation = abs(float(knee["x"]) - float(ankle["x"])) * 100
    hip = landmarks[23] if height_difference > 0 else landmarks[24]
    knee_angle = calcular_angulo(
        [float(hip["x"]), float(hip["y"])],
        [float(knee["x"]), float(knee["y"])],
        [float(ankle["x"]), float(ankle["y"])],
    )
    return {
        "stability": round(max(0, 100 - (deviation * 5)), 2),
        "deviation_cm": round(deviation, 2),
        "angles": {
            "angulo_pierna_soporte": round(float(knee_angle), 2),
            "desviacion_rodilla_tobillo": round(deviation, 2),
        },
        "alignment": "Optima" if deviation < 6 else "Requiere ajuste",
        "alert": deviation >= 6,
        "message": (
            "Ajuste la pierna de apoyo."
            if deviation >= 6
            else "Apoyo unipodal estable."
        ),
    }


def calcular_angulo(punto1, punto2, punto3):
    a = np.array(punto1)
    b = np.array(punto2)
    c = np.array(punto3)
    
    radianes = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angulo = np.abs(radianes * 180.0 / np.pi)
    if angulo > 180.0:
        angulo = 360 - angulo
    return angulo

def ejecutar_apoyo_unipodal(video_source=0):
    """
    Modelo 3: Apoyo Unipodal Intercalado.
    Detecta la elevación de una pierna y evalúa la estabilidad del miembro de soporte.
    """
    if mp_pose is None:
        raise RuntimeError("MediaPipe no está instalado para usar la cámara local.")

    cap = cv2.VideoCapture(video_source)
    alerta_sonora = AlertaSonora()
    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    
    print("Iniciando Modelo 3: Apoyo Unipodal Intercalado. Prepárese frente a la cámara...")

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
            
            # Coordenadas de caderas, rodillas y tobillos de ambos lados
            # Lado Izquierdo
            cadera_izq = [landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].x, landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].y]
            rodilla_izq = [landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].x, landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].y]
            tobillo_izq = [landmarks[mp_pose.PoseLandmark.LEFT_ANKLE.value].x, landmarks[mp_pose.PoseLandmark.LEFT_ANKLE.value].y]
            
            # Lado Derecho
            cadera_der = [landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value].y]
            rodilla_der = [landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value].y]
            tobillo_der = [landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE.value].x, landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE.value].y]
            
            # Evaluar altura de los tobillos para determinar qué pierna está levantada
            # En MediaPipe, el eje Y aumenta hacia abajo, por lo que un valor menor en Y significa que el pie está más arriba.
            diferencia_altura_pies = tobillo_izq[1] - tobillo_der[1]
            
            if diferencia_altura_pies < -0.05:
                # Pie izquierdo elevado -> Apoyo sobre la pierna derecha
                angulo_soporte = calcular_angulo(cadera_der, rodilla_der, tobillo_der)
                modo_texto = "Soporte: Pierna DERECHA (Izquierda elevada)"
                color_estado = (0, 255, 0)
            elif diferencia_altura_pies > 0.05:
                # Pie derecho elevado -> Apoyo sobre la pierna izquierda
                angulo_soporte = calcular_angulo(cadera_izq, rodilla_izq, tobillo_izq)
                modo_texto = "Soporte: Pierna IZQUIERDA (Derecha elevada)"
                color_estado = (0, 255, 0)
            else:
                modo_texto = "Colocandose en posicion unipodal..."
                color_estado = (0, 165, 255)
                alerta_sonora.emitir()

            # Mostrar información en pantalla
            cv2.putText(image, f'Ejercicio: Apoyo Unipodal', (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(image, modo_texto, (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_estado, 2)
            cv2.putText(image, 'Presione "q" para salir', (30, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
        except Exception as e:
            cv2.putText(image, 'Ajuste su postura frente a la camara', (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if results.pose_landmarks:
            mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

        cv2.imshow('Modelo 3: Apoyo Unipodal Intercalado', image)
        
        if cv2.waitKey(10) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    ejecutar_apoyo_unipodal()