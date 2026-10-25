"""El oído de NAVI: graba del micrófono y transcribe con Whisper, 100% local.

El micrófono solo se enciende cuando lo pides (Enter vacío) y se apaga
solo cuando dejas de hablar. El audio nunca sale de tu PC.
"""

import os
import select
import shutil
import subprocess
import sys
import threading

import numpy as np

from . import config

TASA = 16000            # Whisper trabaja a 16 kHz
BLOQUE = TASA // 10     # leemos el micrófono en trozos de 0.1 s

# Pista de vocabulario: ayuda a Whisper a entender nombres raros
PISTA = ("Conversación con NAVI, la computadora de Lain. Hola NAVI, abre Firefox "
         "en el workspace 2. ¿Hay actualizaciones? En la actualidad, en este momento. El Nexo.")

# Frases que Whisper "alucina" cuando solo oye ruido
_ALUCINACIONES = ("amara.org", "subtítulos", "gracias por ver", "suscríbete")


def _microfono() -> str | None:
    """Qué micrófono usar. "interno" busca el del PC (no Bluetooth ni USB)."""
    elegido = config.OIDO_MICROFONO
    if elegido != "interno":
        return elegido or None  # vacío = el predeterminado del sistema
    if not shutil.which("pactl"):
        return None
    r = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True)
    for linea in r.stdout.splitlines():
        nombre = linea.split("\t")[1] if "\t" in linea else ""
        if nombre.startswith("alsa_input.pci") and not nombre.endswith(".monitor"):
            return nombre
    return None


def _comando_grabar() -> list[str] | None:
    if shutil.which("pw-record"):
        destino = ["--target", _microfono()] if _microfono() else []
        return ["pw-record", "--raw", "--rate", str(TASA), "--channels", "1",
                "--format", "s16", *destino, "-"]
    if shutil.which("parecord"):
        destino = [f"--device={_microfono()}"] if _microfono() else []
        return ["parecord", "--raw", f"--rate={TASA}", "--channels=1", "--format=s16le",
                *destino]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", str(TASA), "-c", "1", "-t", "raw"]
    return None


def _leer(proceso: subprocess.Popen, cantidad: int, espera: float) -> bytes | None:
    """Lee `cantidad` bytes del grabador. None si el micro deja de mandar audio."""
    fd = proceso.stdout.fileno()
    datos = b""
    while len(datos) < cantidad:
        listo, _, _ = select.select([fd], [], [], espera)
        if not listo:
            return None
        trozo = os.read(fd, cantidad - len(datos))
        if not trozo:
            break  # el grabador terminó
        datos += trozo
    return datos


def _enter_presionado() -> bool:
    """¿Presionaste Enter mientras grababa? (sin bloquear)"""
    if not sys.stdin.isatty():
        return False
    listo, _, _ = select.select([sys.stdin], [], [], 0)
    if listo:
        sys.stdin.readline()  # consumimos el Enter para que no quede pendiente
        return True
    return False


class Oido:
    def __init__(self) -> None:
        self._grabar = _comando_grabar()
        self._modelo = None
        self._listo = threading.Event()
        self.problema: str | None = None
        if self.disponible:
            # Cargamos Whisper en segundo plano para no demorar el arranque
            threading.Thread(target=self._cargar, daemon=True).start()

    @property
    def disponible(self) -> bool:
        return config.OIDO_MODELO != "ninguno" and self._grabar is not None

    def _cargar(self) -> None:
        from faster_whisper import WhisperModel
        self._modelo = WhisperModel(config.OIDO_MODELO, device="cpu", compute_type="int8",
                                    download_root=str(config.RAIZ / "modelos"))
        self._listo.set()

    def escuchar(self, max_segundos: float = 10, silencio_final: float = 1.2,
                 espera_maxima: float = 6) -> np.ndarray:
        """Graba hasta que dejes de hablar (o presiones Enter).
        Devuelve audio vacío si nadie habló; en ese caso self.problema
        explica si fue culpa del micrófono."""
        self.problema = None
        proceso = subprocess.Popen(self._grabar, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        trozos: list[np.ndarray] = []
        ruido: list[float] = []
        umbral = None
        pico = 0.0       # qué tan fuerte hablas tú (promedio móvil)
        hablando = False
        silencio = 0.0
        try:
            for i in range(int(max_segundos * 10)):
                datos = _leer(proceso, BLOQUE * 2, espera=2.0)
                if datos is None:
                    self.problema = ("El micrófono no manda audio. Si es Bluetooth, "
                                     "prueba con NAVI_MICROFONO=interno en tu .env.")
                    break
                if not datos:
                    break
                if _enter_presionado():
                    trozos.append(np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768)
                    hablando = hablando or umbral is not None
                    break
                trozo = np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768
                volumen = float(np.sqrt(np.mean(trozo ** 2)))

                # Las primeras 0.3 s miden el ruido de fondo de tu cuarto
                if umbral is None:
                    ruido.append(volumen)
                    if len(ruido) == 3:
                        if max(ruido) == 0:
                            # Ceros perfectos: ni un micro barato es tan silencioso
                            self.problema = ("El micrófono está silenciado. Actívalo con: "
                                             "amixer -c 0 sset Capture cap")
                            break
                        umbral = max(np.mean(ruido) * 3, 0.01)
                    continue

                trozos.append(trozo)
                # Tú estás pegada al micro: lo que suene mucho más bajo que tu voz
                # (gente de fondo, la tele) cuenta como silencio
                corte = max(umbral, pico * 0.3)
                if volumen > corte:
                    hablando = True
                    silencio = 0.0
                    pico = volumen if pico == 0 else max(pico * 0.9 + volumen * 0.1, pico * 0.98)
                elif hablando:
                    silencio += 0.1
                    if silencio >= silencio_final:
                        break
                elif i / 10 > espera_maxima:
                    break  # nadie habló
        finally:
            proceso.terminate()
            proceso.wait()

        if not hablando:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(trozos)

    def transcribir(self, audio: np.ndarray) -> str:
        if len(audio) == 0:
            return ""
        self._listo.wait()
        segmentos, _ = self._modelo.transcribe(audio, language="es", beam_size=1,
                                               vad_filter=True, initial_prompt=PISTA)
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        if any(a in texto.lower() for a in _ALUCINACIONES):
            return ""
        return texto


def medidor(segundos: int = 10) -> None:
    """Muestra el volumen del micrófono en vivo para ajustar NAVI: python -m navi.oido"""
    comando = _comando_grabar()
    if comando is None:
        sys.exit("No encontré pw-record, parecord ni arecord.")
    print(f"Midiendo el micrófono {segundos} s. Quédate callada 3 s y luego habla normal.\n")
    proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    volumenes = []
    try:
        for i in range(segundos * 10):
            datos = proceso.stdout.read(BLOQUE * 2)
            if not datos:
                break
            trozo = np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768
            v = float(np.sqrt(np.mean(trozo ** 2)))
            volumenes.append(v)
            barra = "█" * min(int(v * 300), 60)
            print(f"\r{i / 10:4.1f}s {v:.3f} {barra:<60}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proceso.terminate()
        proceso.wait()
    if len(volumenes) >= 40:
        fondo = float(np.median(volumenes[:30]))
        voz = float(np.percentile(volumenes[30:], 90))
        print(f"\n\nRuido de fondo: {fondo:.3f}   Tu voz: {voz:.3f}   "
              f"Relación: {voz / max(fondo, 1e-4):.1f}x")
        if voz / max(fondo, 1e-4) < 3:
            print("Tu voz apenas supera el ruido: acércate al micrófono o baja su volumen.")
        elif fondo > 0.05:
            print("El ruido de fondo es alto: prueba bajar el volumen del micrófono.")
        else:
            print("Se ve bien: NAVI debería distinguirte del ruido.")


if __name__ == "__main__":
    medidor()
