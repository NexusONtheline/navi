"""Portapapeles (wl-clipboard en Wayland, xclip en X11): leer lo copiado y copiar textos.

Lo que se lee se envía a Gemini, así que se rechaza lo que parezca una
contraseña o un dato sensible.
"""

import re
import shutil
import subprocess

from .. import memoria
from ..escritorio import en_wayland

_LIMITE = 12000  # caracteres: suficiente para un artículo, sin gastar demasiada cuota


def _parece_contrasena(texto: str) -> bool:
    """Una sola "palabra" que mezcla letras, números y/o símbolos: típico de una contraseña."""
    t = texto.strip()
    if not t or re.search(r"\s", t) or not 6 <= len(t) <= 128 or t.startswith(("http://", "https://")):
        return False
    tipos = sum(bool(re.search(patron, t))
                for patron in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    return tipos >= 3


def leer_portapapeles() -> str:
    """Lee el texto que el usuario copió (Ctrl+C), para resumirlo, traducirlo,
    explicarlo, corregirlo, etc. Úsala SOLO cuando el usuario se refiera
    explícitamente a "lo que copié" o "el portapapeles"."""
    if en_wayland() and shutil.which("wl-paste"):
        tipos = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True).stdout
        leer = ["wl-paste", "--no-newline", "--type", "text/plain"]
    elif shutil.which("xclip"):
        tipos = subprocess.run(["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
                               capture_output=True, text=True).stdout
        leer = ["xclip", "-selection", "clipboard", "-o"]
    else:
        return "Necesito wl-clipboard (Wayland) o xclip (X11) para leer el portapapeles."
    if not tipos.strip():
        return "El portapapeles está vacío."
    if "text/plain" not in tipos and "UTF8_STRING" not in tipos and "STRING" not in tipos:
        return "Lo que hay copiado no es texto (puede ser una imagen o un archivo)."
    texto = subprocess.run(leer, capture_output=True, text=True, errors="replace").stdout
    if not texto.strip():
        return "El portapapeles está vacío."
    if _parece_contrasena(texto) or memoria.es_sensible(texto[:500]):
        return ("No lo leí: lo que está copiado parece una contraseña o un dato "
                "sensible, y no debe salir de este PC.")
    if len(texto) > _LIMITE:
        return texto[:_LIMITE] + f"\n[... recortado: el texto completo tiene {len(texto)} caracteres]"
    return texto


def copiar_al_portapapeles(texto: str) -> str:
    """Copia un texto al portapapeles para que el usuario lo pegue con Ctrl+V.
    Útil después de traducir, resumir o corregir algo.

    Args:
        texto: El texto exacto a copiar, sin comentarios añadidos.
    """
    if en_wayland() and shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=texto, text=True)
    elif shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=texto, text=True)
    else:
        return "Necesito wl-clipboard (Wayland) o xclip (X11) para copiar."
    return "Copiado al portapapeles: ya puedes pegarlo con Ctrl+V."


HERRAMIENTAS = [leer_portapapeles, copiar_al_portapapeles]
