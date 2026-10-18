import time
import winsound

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None


class AlertaSonora:
    """Emite pitidos y mensajes de voz sin repetirlos continuamente."""

    def __init__(
        self,
        intervalo=1.5,
        frecuencia=1000,
        duracion=180,
        velocidad_voz=150,
    ):
        if intervalo < 0:
            raise ValueError("El intervalo no puede ser negativo.")
        if frecuencia <= 0:
            raise ValueError("La frecuencia debe ser mayor que cero.")
        if duracion <= 0:
            raise ValueError("La duración debe ser mayor que cero.")

        self.intervalo = intervalo
        self.frecuencia = frecuencia
        self.duracion = duracion
        self.velocidad_voz = velocidad_voz
        self._ultima_alerta = 0.0
        self._ultimo_estado = None

    @property
    def ultimo_estado(self):
        return self._ultimo_estado

    def emitir(self):
        ahora = time.monotonic()
        if ahora - self._ultima_alerta < self.intervalo:
            return

        winsound.Beep(self.frecuencia, self.duracion)
        self._ultima_alerta = ahora

    def anunciar_estado(self, estado):
        """Anuncia un estado solo cuando cambia.

        Si la síntesis de voz no está instalada o falla, se conserva el pitido
        como respaldo para no perder la alerta.
        """
        estados = {
            "correcta": "Postura correcta.",
            "incorrecta": "Postura incorrecta. Corrija su postura.",
            "corregida": "Postura corregida. Postura correcta.",
        }
        mensaje = estados.get(estado)
        if mensaje is None or estado == self._ultimo_estado:
            return

        self._ultimo_estado = estado
        if pyttsx3 is None:
            self.emitir()
            return

        try:
            motor = pyttsx3.init()
            motor.setProperty("rate", self.velocidad_voz)
            motor.say(mensaje)
            motor.runAndWait()
            motor.stop()
        except Exception:
            self.emitir()
