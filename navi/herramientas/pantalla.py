"""Ver la pantalla: captura una ventana (o la pantalla) y Gemini la analiza.

La captura se envía a Google, así que la interfaz de NAVI siempre le pide
permiso al usuario directamente antes (sin pasar por la IA). La imagen se
borra al acabar.
"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import types

from .. import config, confirmaciones
from ..escritorio import en_sway
from .ventanas import _buscar, _es_navi, _swaymsg, _ventanas

_INSTRUCCIONES = (
    "Eres NAVI, la asistente del usuario. Mira esta captura de su pantalla y responde "
    "en español, breve y claro, a lo que pregunta. Si hay un mensaje de error, "
    "cópialo tal cual y explica cómo solucionarlo paso a paso. Si aparecen "
    "contraseñas, códigos o datos bancarios, no los repitas.\n\nPregunta: "
)


def _se_solapan(a: dict, b: dict) -> bool:
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])


def _capturar(ventana: dict | None) -> bytes:
    """JPEG de la ventana indicada (o de toda la pantalla si es None)."""
    navi = next((v for v in _ventanas() if _es_navi(v)), None)
    escondida = None
    if ventana is not None:
        if not ventana["visible"]:  # está en otro workspace: vamos a verla
            _swaymsg(f"[con_id={int(ventana['id'])}] focus")
            time.sleep(0.4)
        # Una NAVI flotante encima taparía justo lo que queremos ver
        if navi and navi["flotante"] and _se_solapan(navi["rect"], ventana["rect"]):
            escondida = navi
            _swaymsg(f"[con_id={int(navi['id'])}] move scratchpad")
            time.sleep(0.3)

    with tempfile.TemporaryDirectory() as carpeta:
        archivo = Path(carpeta) / "captura.jpg"
        args = ["grim", "-t", "jpeg", "-q", "80"]
        if ventana is not None:
            r = ventana["rect"]
            args += ["-g", f"{r['x']},{r['y']} {r['width']}x{r['height']}"]
        try:
            subprocess.run([*args, str(archivo)], check=True, capture_output=True, timeout=10)
            return archivo.read_bytes()
        finally:
            if escondida:  # la devolvemos a su sitio
                _swaymsg(f"[con_id={int(escondida['id'])}] scratchpad show")
            if navi:
                _swaymsg(f"[con_id={int(navi['id'])}] focus")


def _capturar_x11() -> tuple[bytes, str]:
    """Pantalla completa fuera de Sway (Cinnamon, XFCE...) con la herramienta que haya."""
    with tempfile.TemporaryDirectory() as carpeta:
        archivo = Path(carpeta) / "captura.png"
        for comando in (["gnome-screenshot", "-f", str(archivo)],
                        ["scrot", "-o", str(archivo)],
                        ["import", "-window", "root", str(archivo)],
                        ["grim", str(archivo)]):
            if shutil.which(comando[0]):
                subprocess.run(comando, capture_output=True, timeout=15)
                if archivo.exists() and archivo.stat().st_size:
                    return archivo.read_bytes(), "image/png"
    raise OSError("no encontré ninguna herramienta de capturas (gnome-screenshot o scrot)")


def ver_pantalla(pregunta: str, toda_la_pantalla: bool = False, app: str = "") -> str:
    """Mira la pantalla del usuario para responder sobre lo que se ve en ella:
    "¿qué hay en mi pantalla?", "¿qué tienes enfrente?", "ayúdame con este error".
    Llámala directamente: NAVI le pedirá permiso al usuario antes de capturar.

    Args:
        pregunta: Qué quiere saber el usuario sobre su pantalla.
        toda_la_pantalla: True solo si pide ver toda la pantalla. Por defecto se
            captura una sola ventana (más privado).
        app: Ventana a mirar ("firefox", "terminal"...). Vacío = la última que usó
            antes de hablar con NAVI.
    """
    sway = en_sway()
    if sway and shutil.which("grim") is None:
        return "Necesito grim instalado para capturar la pantalla."
    # Fuera de Sway no sabemos recortar una ventana: se captura la pantalla entera
    ventana = None if toda_la_pantalla or not sway else _buscar(app)
    if isinstance(ventana, str):
        return ventana
    que = "toda tu pantalla" if ventana is None else f"la ventana de {ventana['app']}"
    if not confirmaciones.preguntar(f"¿Me dejas capturar {que}? "
                                    "La imagen se enviará a Google y luego se borra."):
        return ("Respondió que no, así que no capturé nada. Contéstale de tú, en una "
                "frase y sin volver a preguntar, algo como: «Vale, no miro tu pantalla.»")

    try:
        imagen, tipo = (_capturar(ventana), "image/jpeg") if sway else _capturar_x11()
    except (subprocess.SubprocessError, OSError) as e:
        return f"No pude capturar la pantalla: {e}"

    cliente = genai.Client(api_key=config.GEMINI_API_KEY)
    respuesta = cliente.models.generate_content(
        model=config.GEMINI_MODELO,
        contents=[types.Part.from_bytes(data=imagen, mime_type=tipo),
                  _INSTRUCCIONES + pregunta],
    )
    return (respuesta.text or "No pude interpretar la imagen.").strip()


HERRAMIENTAS = [ver_pantalla]
