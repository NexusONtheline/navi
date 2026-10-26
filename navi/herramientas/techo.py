"""Modo techo y holograma, en el proyector HDMI que apunta al techo.

- Techo: barras de audio moradas. Lo hace techo.sh (en la raíz del proyecto), que
  también sirve solo desde la terminal.
- Holograma: NAVI de cuerpo entero (navi/holograma.py). Lo dibuja la mascota, así
  que le mandamos las órdenes por la tubería de senales. Si el holograma está
  encendido, las barras del techo se ponen a sus pies en vez de abrir otra ventana.

cava solo dibuja el sonido en vivo: no graba ni envía nada.
"""

import os
import re
import subprocess
import time
import unicodedata

from .. import config, senales

_SCRIPT = config.RAIZ / "techo.sh"
_MODO_TECHO = senales.CARPETA / "techo.modo"
_HOLOGRAMA = senales.CARPETA / "holograma"  # lo escribe la mascota: «pid barras estilo»
_MASCOTA = senales.CARPETA / "mascota.pid"


def _techo(*args: str) -> str:
    try:
        r = subprocess.run([str(_SCRIPT), *args], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return "El techo tardó demasiado en responder."
    except OSError as e:
        return f"No pude ejecutar techo.sh ({e})."
    return (r.stdout or r.stderr).strip() or "Listo."


def _modo(texto: str) -> str:
    return "voz" if "voz" in texto.lower() or "micro" in texto.lower() else "musica"


def _campos_si_vive(ruta) -> list[str] | None:
    """Lo que dice el archivo `ruta` («pid ...»), si ese proceso sigue vivo."""
    try:
        campos = ruta.read_text().split()
        os.kill(int(campos[0]), 0)
    except (OSError, ValueError, IndexError):
        return None
    return campos


def _holograma() -> tuple[bool, str | None]:
    """(¿está encendido?, modo de sus barras o None)."""
    campos = _campos_si_vive(_HOLOGRAMA)
    if not campos:
        return False, None
    return True, campos[1] if len(campos) > 1 and campos[1] != "-" else None


def _esperar(condicion, segundos: float = 4) -> bool:
    """Las órdenes a la mascota tardan un instante: esperamos a ver que se cumplan."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.1)
    return False


def _nombre(modo: str) -> str:
    return "tu voz" if modo == "voz" else "la música"


def encender_techo(modo: str = "musica") -> str:
    """Enciende el modo techo: un visualizador de audio en el proyector HDMI que apunta al techo.

    Args:
        modo: "musica" para lo que suena en los parlantes, "voz" para el micrófono.
    """
    modo = _modo(modo)
    if _holograma()[0]:
        senales.avisar_a_navi(f"barras:{modo}")
        if _esperar(lambda: _holograma()[1] == modo):
            return f"Puse las barras con {_nombre(modo)} a los pies del holograma."
        return "No pude poner las barras en el holograma."
    return _techo(modo)


def apagar_techo() -> str:
    """Apaga el modo techo (las barras de audio) y cierra su ventana."""
    encendido, barras = _holograma()
    if encendido and barras:
        senales.avisar_a_navi("barras:apagar")
        _esperar(lambda: _holograma()[1] is None)
        return "Quité las barras del holograma."
    return _techo("apagar")


def encender_holograma(barras: str = "", estilo: str = "") -> str:
    """Muestra a NAVI como holograma de cuerpo entero en el proyector HDMI (techo o pared).
    Se mueve, escucha y habla igual que la mascota. También sirve para cambiarle el estilo.

    Args:
        barras: "musica" o "voz" para poner a sus pies las barras de audio del modo techo;
            vacío para no añadirlas (si el techo ya estaba encendido, sus barras se quedan).
        estilo: "color" (beige, como la mascota) o "lineas" (hecho de luz morada);
            vacío para dejar el que tenga.
    """
    estilo = ("lineas" if any(p in estilo.lower() for p in ("line", "líne", "luz"))
              else "color" if estilo.strip() else "")
    if estilo:
        senales.avisar_a_navi(f"estilo:{estilo}")
    if _holograma()[0] and estilo and not barras.strip():  # ya estaba: solo cambia el estilo
        nombre = "de luz" if estilo == "lineas" else "a color"
        if _esperar(lambda: (_campos_si_vive(_HOLOGRAMA) or [""])[-1] == estilo):
            return f"Listo, ahora el holograma es {nombre}."
        return "No pude cambiar el estilo del holograma."
    if not _campos_si_vive(_MASCOTA):
        return ("El holograma vive dentro de la mascota: ábrela con «navi --mascota» "
                "y vuelve a pedírmelo.")
    r = subprocess.run([str(_SCRIPT), "preparar"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return r.stdout.strip() or "No pude preparar el proyector."
    salida = r.stdout.strip()
    modo = _modo(barras) if barras.strip() else None
    if _campos_si_vive(senales.CARPETA / "techo.pid"):  # el techo estaba encendido:
        if not modo:  # sus barras pasan al holograma
            modo = _MODO_TECHO.read_text().strip() if _MODO_TECHO.exists() else "musica"
        _techo("apagar")
    senales.avisar_a_navi(f"holograma:{salida}")
    if not _esperar(lambda: _holograma()[0]):
        return "Le pedí a la mascota el holograma, pero no apareció."
    if modo:
        senales.avisar_a_navi(f"barras:{modo}")
        _esperar(lambda: _holograma()[1] == modo)
        return f"Holograma encendido en {salida}, con las barras de {_nombre(modo)}."
    return f"Holograma encendido en {salida}."


def apagar_holograma() -> str:
    """Apaga el holograma de NAVI (y las barras que tuviera a sus pies)."""
    if not _holograma()[0]:
        return "El holograma ya estaba apagado."
    senales.avisar_a_navi("holograma-apagar")
    if _esperar(lambda: not _holograma()[0]):
        return "Holograma apagado."
    return "No pude apagar el holograma."


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
    "holograma": encender_holograma,
    "holograma musica": lambda: encender_holograma("musica"),
    "holograma con musica": lambda: encender_holograma("musica"),
    "holograma voz": lambda: encender_holograma("voz"),
    "holograma con voz": lambda: encender_holograma("voz"),
    "apaga el holograma": apagar_holograma,
    "apaga holograma": apagar_holograma,
    "apagar holograma": apagar_holograma,
    "apagar el holograma": apagar_holograma,
    "quita el holograma": apagar_holograma,
    "holograma lineas": lambda: encender_holograma(estilo="lineas"),
    "holograma de lineas": lambda: encender_holograma(estilo="lineas"),
    "holograma de luz": lambda: encender_holograma(estilo="lineas"),
    "holograma color": lambda: encender_holograma(estilo="color"),
    "holograma a color": lambda: encender_holograma(estilo="color"),
    "holograma en color": lambda: encender_holograma(estilo="color"),
    "holograma apagar": apagar_holograma,
}


def atajo(mensaje: str) -> str | None:
    """Si el mensaje es justo una orden del techo, la cumple sin preguntarle a la IA."""
    orden = _ATAJOS.get(_normalizar(mensaje))
    return orden() if orden else None


HERRAMIENTAS = [encender_techo, apagar_techo, encender_holograma, apagar_holograma]
ATAJOS = [atajo]
