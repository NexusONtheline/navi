"""Buscar en internet (DuckDuckGo, gratis y sin API key) y abrir enlaces.

La búsqueda de Google integrada en Gemini no entra en la capa gratuita,
así que buscamos con DuckDuckGo y Gemini resume los resultados.
"""

import shutil
import subprocess
from urllib.parse import urlparse


def buscar_en_internet(consulta: str, cantidad: int = 6) -> str:
    """Busca en internet y devuelve títulos, enlaces y un extracto de cada resultado.
    Úsala para información actual o que no sabes: series, noticias, horarios,
    precios, lugares, etc. Cita los enlaces cuando sean útiles.

    Args:
        consulta: Qué buscar, con palabras clave claras. Por ejemplo
            "serie documental podólogos dónde ver".
        cantidad: Cuántos resultados traer, de 1 a 10.
    """
    try:
        from ddgs import DDGS
        resultados = DDGS().text(consulta, region="es-es", safesearch="moderate",
                                 max_results=max(1, min(int(cantidad), 10)))
    except Exception as e:  # la librería lanza varios tipos según el fallo
        return f"No pude buscar en internet ahora mismo ({type(e).__name__}). Intenta en un rato."
    if not resultados:
        return f"No encontré nada sobre «{consulta}»."
    return "\n\n".join(
        f"{i}. {r.get('title', '')}\n   {r.get('href', '')}\n   {r.get('body', '')[:250]}"
        for i, r in enumerate(resultados, 1)
    )


def abrir_enlace(url: str) -> str:
    """Abre una página web en el navegador del usuario.

    Args:
        url: Dirección completa que empiece por http:// o https://.
    """
    partes = urlparse(url.strip())
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return f"Ese enlace no parece válido: {url}"
    if shutil.which("xdg-open") is None:
        return "No encontré xdg-open para abrir el navegador."
    subprocess.Popen(["xdg-open", url.strip()], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Abrí {partes.netloc} en el navegador."


HERRAMIENTAS = [buscar_en_internet, abrir_enlace]
