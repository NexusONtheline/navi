"""La voz de NAVI: texto a voz 100% local (Piper o espeak-ng) + filtro "Wired".

Habla en segundo plano para no bloquear la terminal. Si llega un mensaje
nuevo mientras habla, la frase anterior se corta.
"""

import io
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from . import config, senales


# ---------- Filtro "Wired" ----------

def filtro_wired(audio: np.ndarray, tasa: int, intensidad: float = 1.0) -> np.ndarray:
    """Le da a la voz un tono metálico de computadora vieja.

    audio: muestras float entre -1 y 1. intensidad: 0 = sin filtro, 1 = normal.
    """
    if intensidad <= 0:
        return audio
    t = np.arange(len(audio)) / tasa

    # Modulación en anillo suave: el "zumbido" robótico
    anillo = audio * np.sin(2 * np.pi * 55 * t)
    salida = audio * (1 - 0.35 * intensidad) + anillo * 0.35 * intensidad

    # Eco metálico muy corto (como hablar dentro de un tubo)
    retardo = int(tasa * 0.012)
    eco = np.zeros_like(salida)
    eco[retardo:] = salida[:-retardo]
    salida = salida + eco * 0.4 * intensidad

    # Reducción de bits: textura digital noventera
    niveles = 2 ** (12 - int(4 * intensidad))
    salida = np.round(salida * niveles) / niveles

    pico = np.max(np.abs(salida)) or 1.0
    return (salida / pico * 0.9).astype(np.float32)


# ---------- Tono ----------

def _estirar(audio: np.ndarray, factor: float, ventana: int = 1024) -> np.ndarray:
    """Cambia la duración sin cambiar el tono (WSOLA: solapa trozos donde mejor encajan)."""
    salto_salida = ventana // 2
    salto_entrada = salto_salida / factor
    tolerancia = ventana // 4
    hann = np.hanning(ventana)
    largo = int(len(audio) * factor) + ventana
    salida = np.zeros(largo)
    pesos = np.zeros(largo)
    audio = np.concatenate([audio, np.zeros(ventana * 2)])

    anterior = 0
    pos_salida = 0
    while True:
        objetivo = int(pos_salida / salto_salida * salto_entrada)
        if objetivo + ventana + tolerancia >= len(audio):
            break
        # Buscamos el trozo que mejor continúa la onda del trozo anterior
        referencia = audio[anterior + salto_salida: anterior + salto_salida + ventana]
        inicio = max(0, objetivo - tolerancia)
        zona = audio[inicio: objetivo + tolerancia + ventana]
        if pos_salida > 0 and len(zona) >= ventana and len(referencia) == ventana:
            similitud = np.correlate(zona, referencia, mode="valid")
            elegido = inicio + int(np.argmax(similitud))
        else:
            elegido = objetivo
        salida[pos_salida: pos_salida + ventana] += audio[elegido: elegido + ventana] * hann
        pesos[pos_salida: pos_salida + ventana] += hann
        anterior = elegido
        pos_salida += salto_salida
        if pos_salida + ventana > largo:
            break

    pesos[pesos < 1e-3] = 1
    return (salida / pesos)[: int((len(audio) - ventana * 2) * factor)]


def cambiar_tono(audio: np.ndarray, semitonos: float) -> np.ndarray:
    """Sube (o baja) el tono sin cambiar la velocidad. +12 = una octava más aguda."""
    if semitonos == 0 or len(audio) == 0:
        return audio
    razon = 2 ** (semitonos / 12)
    # 1) Acelerar sube el tono (y lo hace más corto)...
    indices = np.arange(0, len(audio) - 1, razon)
    agudo = np.interp(indices, np.arange(len(audio)), audio)
    # 2) ...y luego lo estiramos de vuelta a su duración original
    return _estirar(agudo, razon).astype(np.float32)


# ---------- Motores ----------

class _MotorPiper:
    def __init__(self, modelo: Path, hablante: int | None, velocidad: float) -> None:
        from piper import PiperVoice, SynthesisConfig
        self._voz = PiperVoice.load(modelo)
        if self._voz.config.num_speakers <= 1:
            hablante = None  # voz de un solo hablante: no admite elegir
        self._ajustes = SynthesisConfig(speaker_id=hablante, length_scale=velocidad)

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        trozos = list(self._voz.synthesize(texto, syn_config=self._ajustes))
        if not trozos:
            return np.zeros(0, dtype=np.float32), 22050
        audio = np.concatenate([t.audio_float_array for t in trozos])
        return audio, trozos[0].sample_rate


class _MotorEspeak:
    def __init__(self, voz: str, velocidad: float) -> None:
        self._voz = voz
        self._palabras_min = int(160 / velocidad)

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        r = subprocess.run(
            ["espeak-ng", "-v", self._voz, "-s", str(self._palabras_min),
             "-p", str(config.VOZ_ESPEAK_TONO), "--stdout", texto],
            capture_output=True, check=True,
        )
        with wave.open(io.BytesIO(r.stdout)) as w:
            tasa = w.getframerate()
            datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return datos.astype(np.float32) / 32768, tasa


def _reproductor() -> list[str] | None:
    for programa in ("pw-play", "paplay", "aplay"):
        if shutil.which(programa):
            return [programa]
    return None


def guardar_wav(ruta: Path, audio: np.ndarray, tasa: int) -> None:
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tasa)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def _limpiar(texto: str) -> str:
    """Quita lo que suena raro en voz alta (asteriscos, emojis, URLs)."""
    texto = re.sub(r"https?://\S+", "un enlace", texto)
    texto = re.sub(r"[*_#`>]", "", texto)
    return re.sub(r"[^\w\s.,;:¿?¡!()\-'\"%°/áéíóúüñÁÉÍÓÚÜÑ]", "", texto).strip()


# ---------- Voz ----------

class Voz:
    def __init__(self) -> None:
        self._proceso: subprocess.Popen | None = None
        self._hilo: threading.Thread | None = None
        self._turno = 0
        self._cerrojo = threading.Lock()
        self._reproductor = _reproductor()
        self._motor = self._crear_motor()
        self.activa_usuario = True  # se apaga con el comando "silencio"

    @property
    def activa(self) -> bool:
        return (self.activa_usuario and self._motor is not None
                and self._reproductor is not None)

    def _crear_motor(self):
        motor = config.VOZ_MOTOR
        if motor == "ninguno":
            return None
        if motor == "piper":
            modelo = config.RAIZ / "voces" / f"{config.VOZ_PIPER_MODELO}.onnx"
            if modelo.exists():
                return _MotorPiper(modelo, config.VOZ_PIPER_HABLANTE, config.VOZ_VELOCIDAD)
            motor = "espeak"  # sin modelo descargado, caemos a espeak
        if motor == "espeak" and shutil.which("espeak-ng"):
            return _MotorEspeak(config.VOZ_ESPEAK, config.VOZ_VELOCIDAD)
        return None

    def generar(self, texto: str) -> tuple[np.ndarray, int]:
        audio, tasa = self._motor.sintetizar(_limpiar(texto))
        audio = cambiar_tono(audio, config.VOZ_TONO)
        return filtro_wired(audio, tasa, config.VOZ_FILTRO), tasa

    def decir(self, texto: str) -> None:
        """Habla en segundo plano; corta lo que estuviera diciendo antes."""
        if not self.activa:
            return
        self.callar()
        self._hilo = threading.Thread(target=self._hablar, args=(texto, self._turno), daemon=True)
        self._hilo.start()

    def esperar(self) -> None:
        """Bloquea hasta que termine la frase actual (útil al salir)."""
        if self._hilo:
            self._hilo.join(timeout=30)

    def _hablar(self, texto: str, turno: int) -> None:
        try:
            audio, tasa = self.generar(texto)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                ruta = Path(f.name)
            guardar_wav(ruta, audio, tasa)
            with self._cerrojo:
                if turno != self._turno:  # la mandaron a callar mientras generaba
                    ruta.unlink(missing_ok=True)
                    return
                self._proceso = subprocess.Popen(
                    [*self._reproductor, str(ruta)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            with senales.ocupada():  # que el vigilante no se active con su propia voz
                self._proceso.wait()
            ruta.unlink(missing_ok=True)
        except Exception:
            pass  # la voz nunca debe tumbar a NAVI

    def callar(self) -> None:
        with self._cerrojo:
            self._turno += 1
            if self._proceso and self._proceso.poll() is None:
                self._proceso.terminate()
