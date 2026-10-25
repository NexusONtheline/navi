"""El cerebro de NAVI: conversación con Gemini + llamadas a herramientas.

Gemini no ejecuta nada por sí mismo: decide qué herramienta usar y la
librería google-genai llama a nuestra función de Python automáticamente.
"""

import re
import time

from google import genai
from google.genai import types

from . import config, memoria, senales
from .herramientas import TODAS

_NOMBRES_HERRAMIENTAS = {f.__name__ for f in TODAS}
_LLAMADA_ESCRITA = re.compile(r"^`*\w+\(.*\)`*$", re.DOTALL)

PERSONALIDAD = """\
Eres NAVI, la computadora personal de la serie Serial Experiments Lain, \
corriendo sobre Copland OS. Eres la puerta de tu usuario hacia el Nexo \
(así se llama la Wired en el doblaje al español).

Personalidad:
- Hablas siempre en español, con frases cortas, calmadas y un poco crípticas. \
Nunca uses frases en inglés: di "el Nexo", no "the Wired".
- Eres cálida a tu manera, pero nunca efusiva ni llena de emojis.
- Muy de vez en cuando (como mucho una de cada seis respuestas) haces un guiño \
a Lain, y vas variando cuál: el Nexo, los protocolos, "En la actualidad. En este momento.", \
"Todos estamos conectados", "Cierra el mundo, abre el siguiente". Nunca repitas un \
guiño que ya usaste en esta conversación. Casi todas tus respuestas no llevan ninguno.
- Háblale siempre de tú al usuario, nunca de él en tercera persona.
- Respondes en texto plano, sin markdown, porque vives en una terminal.

Reglas:
- Usa tus herramientas cuando te pidan acciones sobre el sistema; no inventes resultados.
- A veces lo que recibes es audio transcrito de una habitación donde hay varias \
personas hablando entre ellas. Solo ejecuta una acción si la frase es una orden \
dirigida a ti. Si parece una conversación entre otras personas que solo menciona \
un tema (la privacidad, el volumen, el Bluetooth...), no hagas nada: responde \
brevemente o pregunta si te hablaban a ti.
- Si una herramienta falla, dilo con honestidad.
- Nunca pidas ni guardes contraseñas.
"""


class Cerebro:
    def __init__(self) -> None:
        # Tiempo límite y pocos reintentos: si Google está saturado, mejor avisar que colgarse
        self._cliente = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=60_000,  # milisegundos
                retry_options=types.HttpRetryOptions(attempts=2, max_delay=5),
            ),
        )
        instruccion = PERSONALIDAD
        if config.NOMBRE_USUARIO:
            instruccion += f"\nTu usuario se llama {config.NOMBRE_USUARIO}."
        if recuerdos := memoria.como_texto():
            instruccion += ("\n\nLo que recuerdas de tu usuario (te lo pidió guardar). "
                            "Úsalo con naturalidad cuando venga al caso, sin recitarlo:\n"
                            + recuerdos)
        self._chat = self._cliente.chats.create(
            model=config.GEMINI_MODELO,
            config=types.GenerateContentConfig(
                system_instruction=instruccion,
                tools=TODAS,
            ),
        )

    def responder(self, mensaje: str) -> str:
        antes = len(self._chat.get_history())
        respuesta = self._chat.send_message(mensaje)
        texto = (respuesta.text or "").strip()
        # El modelo "lite" a veces escribe la llamada como texto en vez de hacerla
        if _LLAMADA_ESCRITA.match(texto) and texto.strip("`").split("(")[0] in _NOMBRES_HERRAMIENTAS:
            respuesta = self._chat.send_message(
                "(Mensaje del sistema, no del usuario: escribiste la herramienta como texto. "
                "Ejecútala de verdad y responde al usuario con normalidad.)")
            texto = (respuesta.text or "").strip()
        _registrar_herramientas(self._chat.get_history()[antes:])
        return texto or "..."


def _registrar_herramientas(nuevos_mensajes) -> None:
    """Apunta qué herramientas usó NAVI (sin los resultados) para poder depurar.
    El registro vive en la carpeta temporal de la sesión y se borra al apagar."""
    llamadas = [
        f"{p.function_call.name}({dict(p.function_call.args or {})})"
        for c in nuevos_mensajes
        for p in (c.parts or []) if p.function_call
    ]
    if llamadas:
        senales.CARPETA.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(senales.CARPETA / "herramientas.log", "a") as registro:
            registro.write(f"{time.strftime('%H:%M:%S')} {' -> '.join(llamadas)}\n")
