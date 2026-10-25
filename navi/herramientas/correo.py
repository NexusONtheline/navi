"""Preparar correos: NAVI escribe el borrador y lo abre en el navegador.

NAVI nunca envía nada por su cuenta: el usuario revisa el borrador y pulsa
Enviar. Así no hace falta darle a NAVI la contraseña del correo.
"""

import re
import shutil
import subprocess
from urllib.parse import quote, urlencode

from .. import config

_CORREO_VALIDO = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def preparar_correo(para: str, asunto: str, cuerpo: str) -> str:
    """Prepara un correo y lo abre en el navegador para que el usuario lo revise
    y pulse Enviar. NAVI no puede enviarlo sola.

    Si no sabes la dirección del destinatario, pregúntala (o búscala en tu memoria).

    Args:
        para: Dirección de correo del destinatario. Varias, separadas por comas.
        asunto: Asunto breve del correo.
        cuerpo: Texto del correo escrito como lo escribiría el propio usuario: tono
            natural y cotidiano, firmado por él, SIN tu personalidad de NAVI (nada de
            "el Nexo" ni frases de Lain). Incluye los enlaces completos si los hay.
    """
    destinatarios = [d.strip() for d in para.split(",") if d.strip()]
    invalidos = [d for d in destinatarios if not _CORREO_VALIDO.match(d)]
    if not destinatarios or invalidos:
        return f"Esa dirección no parece válida: {', '.join(invalidos) or para}"
    if shutil.which("xdg-open") is None:
        return "No encontré xdg-open para abrir el navegador."

    para = ",".join(destinatarios)
    if config.CORREO == "gmail":
        url = "https://mail.google.com/mail/?" + urlencode(
            {"view": "cm", "fs": "1", "to": para, "su": asunto, "body": cuerpo})
    else:  # el programa de correo predeterminado del sistema
        url = f"mailto:{para}?subject={quote(asunto)}&body={quote(cuerpo)}"
    subprocess.Popen(["xdg-open", url], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return (f"Abrí el borrador para {para} en el navegador. "
            "Dile al usuario que lo revise y pulse Enviar.")


def abrir_correo(buscar: str = "") -> str:
    """Abre la bandeja de entrada de Gmail del usuario en el navegador,
    opcionalmente mostrando el resultado de una búsqueda.

    Args:
        buscar: Búsqueda de Gmail opcional. Admite su sintaxis, por ejemplo
            "from:mama@gmail.com", "is:unread", "universidad" o "has:attachment".
            Vacío para abrir la bandeja de entrada.
    """
    if shutil.which("xdg-open") is None:
        return "No encontré xdg-open para abrir el navegador."
    url = "https://mail.google.com/mail/u/0/#inbox"
    if buscar.strip():
        url = "https://mail.google.com/mail/u/0/#search/" + quote(buscar.strip(), safe="")
    subprocess.Popen(["xdg-open", url], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if buscar.strip():
        return f"Abrí Gmail buscando «{buscar.strip()}»."
    return "Abrí tu bandeja de entrada de Gmail."


HERRAMIENTAS = [preparar_correo, abrir_correo]
