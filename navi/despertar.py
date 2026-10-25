"""El vigilante: escucha en segundo plano hasta oír "NAVI, actívate".

Usa Vosk, 100% local. Solo reconoce un puñado de palabras; no transcribe
ni guarda nada de lo que se dice en la habitación.

Vosk no conoce "navi" ni "actívate", así que la frase le suena a
"nave activa" (o "nadie/navidad activa"). Las palabras "señuelo" atrapan
frases parecidas para que no lo activen por error.
"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config, escritorio, senales
from .oido import TASA, _comando_grabar, _leer

MODELO_VOSK = config.RAIZ / "modelos" / "vosk-model-small-es-0.42"
_SENUELOS = ("nada nadie navidad vida ana la te activo activar actividad nueva "
             "nave activa llave mamá hola oye abre").split()
GRAMATICA = json.dumps(["nave activa", "oye nave activa", *_SENUELOS, "[unk]"],
                       ensure_ascii=False)
FRASE = re.compile(r"\b(nave|nadie|navidad) (activa|activar)\b")
PAUSA_TRAS_ACTIVAR = 4.0  # segundos


def _pitido() -> Path:
    """Dos tonos cortos ascendentes, estilo Copland OS."""
    ruta = senales.CARPETA / "pitido.wav"
    if not ruta.exists():
        from .voz import guardar_wav
        tasa = 22050
        tonos = []
        for frecuencia in (880, 1320):
            t = np.arange(int(tasa * 0.08)) / tasa
            envolvente = np.minimum(1, np.minimum(t, t[::-1]) * 200)
            tonos.append(0.3 * np.sin(2 * np.pi * frecuencia * t) * envolvente)
        guardar_wav(ruta, np.concatenate(tonos), tasa)
    return ruta


def _sonar_pitido() -> None:
    for programa in ("pw-play", "paplay", "aplay"):
        if shutil.which(programa):
            subprocess.Popen([programa, str(_pitido())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def _abrir_navi() -> None:
    """Si NAVI ya está abierta, la trae al frente y le pide que escuche;
    si no, abre su ventana."""
    pid = senales.pid_navi()
    if pid and senales.avisar_a_navi():
        if not escritorio.traer_ventana(pid):
            _registrar("NAVI está abierta pero no encontré su ventana.")
        return
    senales.cerrar_tuberia()  # restos de una NAVI que se cerró a la fuerza
    if not escritorio.abrir_en_terminal([str(config.RAIZ / "navi.sh"), "--escuchar"]):
        _registrar("No encontré ninguna terminal para abrir NAVI.")


def _registrar(texto: str) -> None:
    print(time.strftime("%H:%M:%S"), texto, flush=True)


def vigilar() -> None:
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)

    if not MODELO_VOSK.exists():
        raise SystemExit(f"Falta el modelo de Vosk en {MODELO_VOSK}")
    comando = _comando_grabar()
    if comando is None:
        raise SystemExit("No encontré pw-record, parecord ni arecord.")

    modelo = Model(str(MODELO_VOSK))
    reconocedor = KaldiRecognizer(modelo, TASA, GRAMATICA)
    _registrar("Vigilando. Di «NAVI, actívate».")

    proceso = None
    ultima_activacion = 0.0
    try:
        while True:
            if senales.en_modo_privado():
                if proceso:  # soltamos el micrófono por completo
                    proceso.terminate()
                    proceso.wait()
                    proceso = None
                    _registrar("Modo privado: micrófono liberado.")
                time.sleep(1)
                continue
            if proceso is None:
                proceso = subprocess.Popen(comando, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL)
                _registrar("Micrófono abierto.")

            datos = _leer(proceso, TASA // 4 * 2, espera=3.0)  # trozos de 0.25 s
            if not datos:
                _registrar("El micrófono dejó de mandar audio; reintento.")
                proceso.terminate()
                proceso.wait()
                proceso = None
                time.sleep(2)
                continue

            # Mientras NAVI habla o te escucha, no queremos que se active sola
            if senales.esta_ocupada() or time.time() - ultima_activacion < PAUSA_TRAS_ACTIVAR:
                reconocedor.Reset()
                continue

            if reconocedor.AcceptWaveform(datos):
                texto = json.loads(reconocedor.Result())["text"]
            else:
                texto = json.loads(reconocedor.PartialResult())["partial"]
            if FRASE.search(texto):
                _registrar(f"¡Activada! (oí: {texto!r})")
                ultima_activacion = time.time()
                reconocedor.Reset()
                _sonar_pitido()
                _abrir_navi()
    except KeyboardInterrupt:
        pass
    finally:
        if proceso:
            proceso.terminate()


def main() -> None:
    # Evita que haya dos vigilantes peleando por el micrófono
    import fcntl
    senales.CARPETA.mkdir(mode=0o700, parents=True, exist_ok=True)
    cerrojo = open(senales.CARPETA / "vigilante.lock", "w")
    try:
        fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("El vigilante ya está corriendo.")
    vigilar()


if __name__ == "__main__":
    main()
