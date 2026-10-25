"""Interfaz de terminal con estética Copland OS."""

import os
import random
import select
import sys
import time
from contextlib import contextmanager

from rich.console import Console
from rich.text import Text

consola = Console(highlight=False)

# Paleta inspirada en Copland OS / el Nexo
GRIS = "#8a8a8a"
TEXTO = "#d0d0d0"
ACENTO = "#e0457b"
NAVI = "#9ecbff"

LOGO = r"""
   ______                 __                __   ____  _____
  / ____/___  ____  _____/ /___ _____  ____/ /  / __ \/ ___/
 / /   / __ \/ __ \/ ___/ / __ `/ __ \/ __  /  / / / /\__ \
/ /___/ /_/ / /_/ / /  / / /_/ / / / / /_/ /  / /_/ /___/ /
\____/\____/ .___/_/  /_/\__,_/_/ /_/\__,_/   \____//____/
          /_/
"""

PASOS_ARRANQUE = [
    "NAVI BIOS v0.1 .......................... OK",
    "Memoria del sistema ...................... OK",
    "Cargando Copland OS Enterprise ........... OK",
    "Montando el Nexo (Protocolo 7) ........... OK",
    "Enlazando cerebro remoto ................. OK",
]

FRASES = [
    "En la actualidad. En este momento.",
    "No importa dónde estés, todos estamos conectados.",
    "Cierra el mundo. Abre el siguiente.",
    "El Nexo te escucha.",
]


def arranque(con_oido: bool = False) -> None:
    consola.clear()
    consola.print(Text(LOGO, style=ACENTO))
    for paso in PASOS_ARRANQUE:
        consola.print(Text(paso, style=GRIS))
        time.sleep(0.15)
    consola.print()
    consola.print(Text(random.choice(FRASES), style=f"italic {TEXTO}"))
    if con_oido:
        consola.print(Text("escribe, o presiona Enter vacío para hablarme", style=GRIS))
    consola.print(Text("escribe 'salir' para desconectarte\n", style=GRIS))


def pedir_mensaje(tuberia: int | None = None) -> str | None:
    """Espera a que escribas algo. Devuelve None si el vigilante dijo
    "NAVI, actívate" mientras esperaba (hay que escuchar)."""
    consola.print(Text("> ", style=ACENTO), end="")
    consola.file.flush()
    fuentes = [sys.stdin] + ([tuberia] if tuberia is not None else [])
    listo, _, _ = select.select(fuentes, [], [])
    if tuberia is not None and tuberia in listo:
        os.read(tuberia, 1024)
        consola.print()
        return None
    linea = sys.stdin.readline()
    if not linea:
        raise EOFError
    return linea.strip()


def decir(texto: str) -> None:
    consola.print(Text("NAVI: ", style=f"bold {NAVI}") + Text(texto, style=TEXTO))
    consola.print()


def error(texto: str) -> None:
    consola.print(Text(f"[error] {texto}", style=ACENTO))
    consola.print()


_estado = None  # el indicador "conectando al Nexo..." que esté en pantalla


def pensando():
    global _estado
    _estado = consola.status(Text("conectando al Nexo...", style=GRIS), spinner="dots")
    return _estado


@contextmanager
def pausar_estado():
    """Quita el indicador de espera mientras NAVI le pregunta algo al usuario."""
    if _estado:
        _estado.stop()
    try:
        yield
    finally:
        if _estado:
            _estado.start()


def pista(texto: str) -> None:
    consola.print(Text(texto, style=GRIS))


def escuchando():
    return consola.status(Text("escuchando... (habla, y presiona Enter si no me detengo sola)",
                               style=ACENTO), spinner="point")


def transcribiendo():
    return consola.status(Text("descifrando tu voz...", style=GRIS), spinner="dots")


def mostrar_dictado(texto: str) -> None:
    """Muestra lo que NAVI entendió, como si lo hubieras escrito."""
    consola.print(Text("🎙 ", style=ACENTO) + Text(texto, style=f"italic {TEXTO}"))
