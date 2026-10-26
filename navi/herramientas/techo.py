"""Modo techo: barras de audio moradas proyectadas en el techo con un proyector HDMI.

Todo el trabajo lo hace techo.sh (en la raíz del proyecto), que también sirve solo
desde la terminal. cava solo dibuja el sonido en vivo: no graba ni envía nada.
"""

import re
import subprocess
import unicodedata

from .. import config

_SCRIPT = config.RAIZ / "techo.sh"


def _techo(*args: str) -> str:
    try:
        r = subprocess.run([str(_SCRIPT), *args], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return "El techo tardó demasiado en responder."
    except OSError as e:
        return f"No pude ejecutar techo.sh ({e})."
    return (r.stdout or r.stderr).strip() or "Listo."


def encender_techo(modo: str = "musica") -> str:
    """Enciende el modo techo: un visualizador de audio en el proyector HDMI que apunta al techo.

    Args:
        modo: "musica" para lo que suena en los parlantes, "voz" para el micrófono.
    """
    return _techo("voz" if "voz" in modo.lower() or "micro" in modo.lower() else "musica")


def apagar_techo() -> str:
    """Apaga el modo techo y cierra su ventana."""
    return _techo("apagar")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto.lower()).encode("ascii", "ignore").decode()
    palabras = re.sub(r"[^a-z ]", " ", sin_tildes).split()
    if palabras and palabras[0] == "navi":
        palabras = palabras[1:]
    return " ".join(palabras)


_ATAJOS = {
    "techo": lambda: encender_techo("musica"),
    "techo musica": lambda: encender_techo("musica"),
    "techo voz": lambda: encender_techo("voz"),
    "apaga el techo": apagar_techo,
    "apaga techo": apagar_techo,
    "apagar techo": apagar_techo,
    "apagar el techo": apagar_techo,
    "techo apagar": apagar_techo,
}


def atajo(mensaje: str) -> str | None:
    """Si el mensaje es justo una orden del techo, la cumple sin preguntarle a la IA."""
    orden = _ATAJOS.get(_normalizar(mensaje))
    return orden() if orden else None


HERRAMIENTAS = [encender_techo, apagar_techo]
ATAJOS = [atajo]
