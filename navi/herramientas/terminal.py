"""Ejecutar comandos de terminal, siempre con confirmación del usuario.

La confirmación no pasa por la IA: la interfaz de NAVI le enseña el comando
exacto al usuario y solo lo ejecuta si responde que sí.
"""

import subprocess
from pathlib import Path

from .. import confirmaciones

_ESPERA = 60  # segundos antes de cortar un comando que no termina
_MAX_SALIDA = 3000  # caracteres de salida que le devolvemos a la IA


def _recortar(texto: str) -> str:
    texto = texto.strip()
    if len(texto) <= _MAX_SALIDA:
        return texto
    mitad = _MAX_SALIDA // 2
    return f"{texto[:mitad]}\n[... salida recortada ...]\n{texto[-mitad:]}"


def ejecutar_comando(comando: str) -> str:
    """Ejecuta un comando de terminal (bash) en el PC y devuelve lo que imprime.
    Úsala cuando el usuario pida algo del sistema que tus otras herramientas no
    cubren: ver archivos, espacio en disco, procesos, la IP, instalar con pip, git...
    Llámala directamente: NAVI le enseñará el comando al usuario y le preguntará si
    lo ejecuta. Para abrir programas usa abrir_app, no esta.
    No sirve para comandos interactivos ni con sudo (no hay dónde escribir la
    contraseña): en ese caso dale el comando al usuario para que lo escriba él.

    Args:
        comando: El comando exacto, tal como se escribiría en la terminal,
            por ejemplo "df -h ~" o "ls ~/Descargas".
    """
    comando = comando.strip()
    if not comando:
        return "No me pasaste ningún comando."

    if not confirmaciones.preguntar(f"¿Ejecuto este comando?\n  $ {comando}"):
        return ("Respondió que no, así que no lo ejecuté. Contéstale de tú, en una frase "
                "y sin volver a preguntar, algo como: «Vale, no lo ejecuto.»")

    try:
        r = subprocess.run(["bash", "-c", comando], cwd=Path.home(), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=_ESPERA)
    except subprocess.TimeoutExpired:
        return (f"El comando seguía corriendo después de {_ESPERA} s y lo corté. "
                "Díselo al usuario; si es algo largo, que lo ejecute él en una terminal.")

    salida = _recortar(r.stdout + ("\n" + r.stderr if r.stderr else ""))
    if r.returncode != 0:
        return (f"Falló (código {r.returncode}). Salida:\n{salida or '(nada)'}\n"
                "Explícale el error con honestidad, en pocas palabras.")
    return (f"Hecho (ya lo confirmó). Salida:\n{salida or '(no imprimió nada)'}\n"
            "Resúmele el resultado en pocas frases; no leas la salida entera en voz alta.")


HERRAMIENTAS = [ejecutar_comando]
