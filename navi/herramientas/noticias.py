"""Noticias a la medida: titulares de los temas del usuario, desde feeds RSS.

Los temas activos se guardan en ~/.local/share/navi/noticias.json (personal,
fuera del proyecto). Las fuentes son feeds RSS gratuitos, sin registro.
"""

import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .. import memoria

_UNIVERSO = "https://www.eluniverso.com/arc/outboundfeeds/rss/?outputType=xml"
_UNIVERSO_ENTRETENIMIENTO = ("https://www.eluniverso.com/arc/outboundfeeds/rss/category/"
                             "entretenimiento/?outputType=xml")

# tema: (nombre bonito, [feeds], filtro opcional: solo titulares que lo cumplan)
TEMAS = {
    "anime": ("Anime y cultura japonesa", ["https://ramenparados.com/feed/",
                                           "https://www.animenewsnetwork.com/all/rss.xml"], None),
    "linux": ("Linux y software libre", ["https://www.linuxadictos.com/feed",
                                         "https://www.muylinux.com/feed/"], None),
    "videojuegos": ("Videojuegos", ["https://feeds.weblogssl.com/vidaextra",
                                    "https://www.eurogamer.es/feed"], None),
    "ia": ("Inteligencia artificial", ["https://feeds.weblogssl.com/xataka2"],
           r"\bIA\b|inteligencia artificial|OpenAI|ChatGPT|Gemini|Claude|Anthropic|"
           r"\bLLM\b|modelo de lenguaje|DeepSeek|Copilot"),
    "curiosidades": ("Curiosidades", ["https://www.muyinteresante.com/rss",
                                      "https://feeds.weblogssl.com/xatakaciencia"], None),
    "series": ("Series y películas", ["https://feeds.weblogssl.com/espinof"], None),
    "ciberseguridad": ("Ciberseguridad", ["https://unaaldia.hispasec.com/feed",
                                          "https://www.welivesecurity.com/es/rss/feed/"], None),
    "musica_ecuador": ("Música y conciertos en Ecuador", [_UNIVERSO_ENTRETENIMIENTO, _UNIVERSO],
                       r"concierto|festival|gira|cantante|banda|músic|musical|álbum|"
                       r"\bdisco\b|canción|rapero|reguetón|rock"),
    "ecuador": ("Ecuador", [_UNIVERSO, "https://www.elcomercio.com/feed/"], None),
}
POR_DEFECTO = list(TEMAS)

# Lo típico que no interesa
_EXCLUIR = re.compile(r"bitcoin|cripto|\bbolsa\b|wall street|\bdólar|mercados|"
                      r"acciones de|\bIbex\b|Nasdaq|horóscopo", re.IGNORECASE)

ARCHIVO = memoria.ARCHIVO.parent / "noticias.json"


def _temas_activos() -> list[str]:
    try:
        temas = json.loads(ARCHIVO.read_text())
        return [t for t in temas if t in TEMAS]
    except (OSError, json.JSONDecodeError):
        return POR_DEFECTO


def _guardar_temas(temas: list[str]) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO.write_text(json.dumps(temas, ensure_ascii=False))


def _texto(nodo, *etiquetas: str) -> str:
    for etiqueta in etiquetas:
        valor = nodo.findtext(etiqueta)
        if valor:
            return valor.strip()
    return ""


def _leer_feed(url: str) -> list[dict]:
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NAVI)"})
        raiz = ET.fromstring(urllib.request.urlopen(pedido, timeout=10).read())
    except Exception:  # feed caído o mal formado: lo saltamos sin más
        return []
    atom = "{http://www.w3.org/2005/Atom}"
    noticias = []
    for item in raiz.findall(".//item") or raiz.findall(f".//{atom}entry"):
        enlace = _texto(item, "link")
        if not enlace and (nodo := item.find(f"{atom}link")) is not None:
            enlace = nodo.get("href", "")
        try:
            fecha = parsedate_to_datetime(_texto(item, "pubDate"))
        except (TypeError, ValueError):
            try:
                fecha = datetime.fromisoformat(_texto(item, f"{atom}updated"))
            except ValueError:
                fecha = None
        resumen = re.sub(r"<[^>]+>", " ", _texto(item, "description", f"{atom}summary"))
        noticias.append({
            "titulo": html.unescape(_texto(item, "title", f"{atom}title")).strip(),
            "enlace": enlace.strip(),
            "fecha": fecha,
            "resumen": " ".join(html.unescape(resumen).split())[:220],
        })
    return noticias


def _palabras_clave(titulo: str) -> set[str]:
    return {p for p in re.findall(r"\w+", titulo.lower()) if len(p) > 3}


def _repetida(clave: set[str], vistas: list[set[str]]) -> bool:
    """La misma noticia contada por dos sitios comparte la mayoría de palabras clave."""
    return any(len(clave & otra) >= max(2, min(len(clave), len(otra)) // 3)
               for otra in vistas)


def noticias(tema: str = "", por_tema: int = 3) -> str:
    """Trae los titulares recientes de los temas que le interesan al usuario
    (anime, Linux, videojuegos, IA, curiosidades, series, ciberseguridad, música
    en Ecuador, Ecuador...). Nada de bolsa ni criptomonedas.

    Cómo contarlas: elige 5 titulares de temas DISTINTOS (que haya variedad: anime,
    Linux, Ecuador...), numéralos y cuéntalos en total en menos de un minuto hablado,
    una frase por noticia que parafrasee el titular casi literal. Cuenta cada noticia SOLO con lo que dicen su titular y su
    resumen: nunca mezcles datos de dos noticias distintas ni inventes quién hizo qué.
    Si el titular está en inglés, tradúcelo. Al final pregunta: "¿Quieres más
    información de alguna?". Si el usuario elige una, abre su enlace con abrir_enlace.

    Args:
        tema: Un tema concreto si el usuario lo pide ("noticias de anime"), con una de
            estas claves: anime, linux, videojuegos, ia, curiosidades, series,
            ciberseguridad, musica_ecuador, ecuador. Vacío = todos sus temas.
        por_tema: Cuántos titulares traer de cada tema (1 a 5). Solo se usa con un
            tema concreto: en general se trae el mejor de cada tema, para que haya variedad.
    """
    temas = [tema] if tema in TEMAS else _temas_activos()
    por_tema = max(1, min(int(por_tema), 5)) if tema in TEMAS else 1
    hace_dos_dias = datetime.now(timezone.utc) - timedelta(days=2)

    trabajos = {(t, url) for t in temas for url in TEMAS[t][1]}
    with ThreadPoolExecutor(8) as hilos:
        leidos = dict(zip(trabajos, hilos.map(lambda tu: _leer_feed(tu[1]), trabajos)))

    vistos: list[set[str]] = []
    bloques = []
    numero = 1
    for t in temas:
        nombre, feeds, filtro = TEMAS[t]
        candidatas = [n for url in feeds for n in leidos.get((t, url), [])]
        elegidas = []
        # Primero lo de los últimos 2 días; si el tema anda flojo, lo de la semana
        for limite in (hace_dos_dias, hace_dos_dias - timedelta(days=5)):
            for n in sorted(candidatas, key=lambda n: n["fecha"] or limite, reverse=True):
                clave = _palabras_clave(n["titulo"])
                if (not n["titulo"] or not n["enlace"] or _repetida(clave, vistos)
                        or _EXCLUIR.search(n["titulo"])
                        or (filtro and not re.search(filtro, n["titulo"] + " " + n["resumen"],
                                                      re.IGNORECASE))
                        or (n["fecha"] and n["fecha"].astimezone(timezone.utc) < limite)):
                    continue
                vistos.append(clave)
                elegidas.append(n)
                if len(elegidas) == por_tema:
                    break
            if elegidas:
                break
        if not elegidas:
            continue
        lineas = [f"## {nombre}"]
        for n in elegidas:
            lineas.append(f"[{numero}] {n['titulo']}\n    {n['resumen']}\n    {n['enlace']}")
            numero += 1
        bloques.append("\n".join(lineas))

    if not bloques:
        return "No encontré noticias recientes de tus temas (puede que las fuentes no respondan)."
    return "\n\n".join(bloques)


def temas_de_noticias(accion: str, tema: str = "") -> str:
    """Ve o cambia los temas de las noticias del usuario.

    Args:
        accion: "ver", "agregar" o "quitar".
        tema: Para agregar o quitar: anime, linux, videojuegos, ia, curiosidades,
            series, ciberseguridad, musica_ecuador o ecuador.
    """
    activos = _temas_activos()
    if accion == "ver":
        nombres = ", ".join(TEMAS[t][0] for t in activos) or "ninguno"
        otros = ", ".join(TEMAS[t][0] for t in TEMAS if t not in activos)
        return f"Temas activos: {nombres}." + (f" Disponibles: {otros}." if otros else "")
    if tema not in TEMAS:
        return f"No conozco el tema «{tema}». Disponibles: {', '.join(TEMAS)}."
    if accion == "agregar" and tema not in activos:
        activos.append(tema)
    elif accion == "quitar" and tema in activos:
        activos.remove(tema)
    elif accion not in ("agregar", "quitar"):
        return f"Acción desconocida: {accion}"
    _guardar_temas(activos)
    return f"Listo. Temas activos: {', '.join(TEMAS[t][0] for t in activos) or 'ninguno'}."


HERRAMIENTAS = [noticias, temas_de_noticias]
