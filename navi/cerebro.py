"""El cerebro de NAVI: conversación con una IA gratis + llamadas a herramientas.

La IA no ejecuta nada por sí misma: decide qué herramienta usar y nosotros
llamamos a la función de Python. Hay dos proveedores, cada uno con su clave
gratis en el .env:
- Gemini (Google): la librería google-genai llama a las funciones sola.
- Groq: API compatible con OpenAI; el bucle de herramientas lo hacemos aquí.

Si el que está en uso se satura (pasa a ratos), NAVI salta al siguiente de la
cadena sin perder la conversación, y a los 10 minutos vuelve al principal.
"""

import inspect
import json
import re
import time
import types as tipos_python

import httpx
from google import genai
from google.genai import errors, types

from . import config, memoria, senales
from .herramientas import TODAS

# google-genai usa httpx2 si está instalado (viene con faster-whisper) y si no httpx
try:
    import httpx2
    ERRORES_DE_RED = (httpx.TransportError, httpx2.TransportError)
except ImportError:
    ERRORES_DE_RED = (httpx.TransportError,)

_HERRAMIENTAS = {f.__name__: f for f in TODAS}
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

# Si el principal se satura, NAVI usa el siguiente un rato y luego vuelve
MINUTOS_EN_RESERVA = 10
# Mensajes de conversación que se recuerdan (Groq cuenta tokens por minuto: no muchos)
MEMORIA_DE_CONVERSACION = 16


class Saturado(Exception):
    """El proveedor no puede ahora (saturado, sin cuota, sin respuesta): probar el siguiente."""


class FalloIA(Exception):
    """Un problema que hay que contarle al usuario (clave mala, modelo que no existe...)."""


def _instruccion() -> str:
    instruccion = PERSONALIDAD
    if config.NOMBRE_USUARIO:
        instruccion += f"\nTu usuario se llama {config.NOMBRE_USUARIO}."
    if recuerdos := memoria.como_texto():
        instruccion += ("\n\nLo que recuerdas de tu usuario (te lo pidió guardar). "
                        "Úsalo con naturalidad cuando venga al caso, sin recitarlo:\n"
                        + recuerdos)
    return instruccion


def _registrar_herramientas(llamadas: list[str]) -> None:
    """Apunta qué herramientas usó NAVI (sin los resultados) para poder depurar.
    El registro vive en la carpeta temporal de la sesión y se borra al apagar."""
    if llamadas:
        senales.CARPETA.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(senales.CARPETA / "herramientas.log", "a") as registro:
            registro.write(f"{time.strftime('%H:%M:%S')} {' -> '.join(llamadas)}\n")


# ---------------------------------------------------------------- Gemini

class _Gemini:
    nombre = "Gemini"

    def __init__(self, modelo: str, historial: list[tuple[str, str]]) -> None:
        self.modelo = modelo
        # Tiempo límite corto: a veces Gemini se queda callado sin responder nunca.
        # Lo normal es que conteste en 1-3 s; si no, mejor saltar al siguiente.
        # Guardado en self: si el cliente se pierde, Python lo borra y cierra la conexión
        self._cliente = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=10_000,  # milisegundos, por petición
                                           retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self._chat = self._cliente.chats.create(
            model=modelo,
            config=types.GenerateContentConfig(system_instruction=_instruccion(), tools=TODAS),
            history=[types.Content(role="user" if rol == "user" else "model",
                                   parts=[types.Part(text=texto)]) for rol, texto in historial],
        )

    def responder(self, mensaje: str) -> str:
        try:
            return self._responder(mensaje)
        except ERRORES_DE_RED as e:
            raise Saturado("Gemini no respondió") from e
        except errors.ServerError as e:
            raise Saturado("Gemini está saturado") from e
        except errors.ClientError as e:
            if e.code == 429:  # sin cuota (cada modelo tiene la suya)
                raise Saturado("Gemini: límite gratuito alcanzado") from e
            if e.code in (400, 403) and "API key" in str(e):
                raise FalloIA("La GEMINI_API_KEY no es válida. Revisa tu archivo .env.") from e
            if e.code == 404:
                raise FalloIA(f"El modelo '{self.modelo}' no existe. "
                              "Cambia GEMINI_MODELO en .env.") from e
            raise FalloIA(f"Gemini respondió con un error: {e}") from e

    def _responder(self, mensaje: str) -> str:
        antes = len(self._chat.get_history())
        respuesta = self._chat.send_message(mensaje)
        texto = (respuesta.text or "").strip()
        # El modelo "lite" a veces escribe la llamada como texto en vez de hacerla
        if _LLAMADA_ESCRITA.match(texto) and texto.strip("`").split("(")[0] in _HERRAMIENTAS:
            respuesta = self._chat.send_message(
                "(Mensaje del sistema, no del usuario: escribiste la herramienta como texto. "
                "Ejecútala de verdad y responde al usuario con normalidad.)")
            texto = (respuesta.text or "").strip()
        _registrar_herramientas([
            f"{p.function_call.name}({dict(p.function_call.args or {})})"
            for c in self._chat.get_history()[antes:]
            for p in (c.parts or []) if p.function_call
        ])
        return texto


# ---------------------------------------------------------------- Groq

_TIPOS_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _esquema(funcion) -> dict:
    """La herramienta en el formato de OpenAI/Groq, sacada de su firma y su docstring
    (el mismo docstring que lee Gemini, con su sección «Args:»)."""
    doc = inspect.getdoc(funcion) or ""
    descripcion, _, args = doc.partition("\nArgs:\n")
    explicaciones: dict[str, str] = {}
    actual = None
    for linea in args.splitlines():
        if m := re.match(r"^\s{2,8}(\w+):\s*(.*)$", linea):
            actual = m.group(1)
            explicaciones[actual] = m.group(2)
        elif actual and linea.strip():
            explicaciones[actual] += " " + linea.strip()

    propiedades, obligatorios = {}, []
    for nombre, parametro in inspect.signature(funcion).parameters.items():
        tipo = parametro.annotation
        if isinstance(tipo, tipos_python.UnionType):  # int | None → int
            tipo = next(t for t in tipo.__args__ if t is not type(None))
        propiedades[nombre] = {"type": _TIPOS_JSON.get(tipo, "string"),
                               "description": explicaciones.get(nombre, "")}
        if parametro.default is inspect.Parameter.empty:
            obligatorios.append(nombre)
    return {"type": "function", "function": {
        "name": funcion.__name__, "description": descripcion.strip(),
        "parameters": {"type": "object", "properties": propiedades, "required": obligatorios},
    }}


class _Groq:
    nombre = "Groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"
    ESQUEMAS = [_esquema(f) for f in TODAS]

    def __init__(self, modelo: str, historial: list[tuple[str, str]]) -> None:
        self.modelo = modelo
        self._cliente = httpx.Client(timeout=15, headers={
            "Authorization": f"Bearer {config.GROQ_API_KEY}"})
        self._mensajes: list[dict] = [{"role": rol, "content": texto} for rol, texto in historial]

    def _pedir(self, mensajes: list[dict]) -> dict:
        cuerpo = {"model": self.modelo, "messages": mensajes, "tools": self.ESQUEMAS,
                  "tool_choice": "auto", "temperature": 0.6, "max_completion_tokens": 1024}
        if self.modelo.startswith("openai/gpt-oss"):
            cuerpo["reasoning_effort"] = "low"  # piensa poco: más rápido y gasta menos cuota
        try:
            r = self._cliente.post(self.URL, json=cuerpo)
        except httpx.TransportError as e:
            raise Saturado("Groq no respondió") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise Saturado(f"Groq está saturado ({r.status_code})")
        if r.status_code == 401:
            raise FalloIA("La GROQ_API_KEY no es válida. Revisa tu archivo .env.")
        if r.status_code == 404:
            raise FalloIA(f"El modelo '{self.modelo}' no existe en Groq. Cambia GROQ_MODELO en .env.")
        if r.status_code == 400 and "tool_use_failed" in r.text:
            # El modelo escribió mal una llamada a herramienta: que lo intente el siguiente
            raise Saturado("Groq se enredó con una herramienta")
        if r.status_code != 200:
            raise FalloIA(f"Groq respondió con un error {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]

    def responder(self, mensaje: str) -> str:
        sistema = {"role": "system", "content": _instruccion()}
        turno = [{"role": "user", "content": mensaje}]
        llamadas = []
        try:
            for _ in range(6):  # como mucho 6 rondas de herramientas por mensaje
                respuesta = self._pedir([sistema, *self._mensajes, *turno])
                pedidas = respuesta.get("tool_calls") or []
                if not pedidas:
                    texto = (respuesta.get("content") or "").strip()
                    break
                turno.append({"role": "assistant", "content": respuesta.get("content") or "",
                              "tool_calls": pedidas})
                for pedida in pedidas:
                    nombre = pedida["function"]["name"]
                    resultado = self._ejecutar(nombre, pedida["function"].get("arguments") or "{}")
                    llamadas.append(f"{nombre}({pedida['function'].get('arguments')})")
                    turno.append({"role": "tool", "tool_call_id": pedida["id"],
                                  "content": resultado})
            else:
                texto = "Me enredé con tantas herramientas. ¿Me lo pides de otra forma?"
        finally:
            _registrar_herramientas(llamadas)
        # Para el próximo mensaje basta con lo que se dijo (sin el detalle de las herramientas)
        self._mensajes += [turno[0], {"role": "assistant", "content": texto}]
        self._mensajes = self._mensajes[-MEMORIA_DE_CONVERSACION:]
        return texto

    @staticmethod
    def _ejecutar(nombre: str, argumentos: str) -> str:
        funcion = _HERRAMIENTAS.get(nombre)
        if funcion is None:
            return f"Error: no existe la herramienta {nombre}."
        try:
            return str(funcion(**(json.loads(argumentos) or {})))
        except Exception as e:  # una herramienta rota no debe tumbar la conversación
            return f"Error al ejecutar {nombre}: {type(e).__name__}: {e}"


# ---------------------------------------------------------------- el cerebro

def _cadena() -> list[tuple[type, str]]:
    """Proveedores y modelos en orden de preferencia, según las claves del .env."""
    gemini = [(_Gemini, m) for m in dict.fromkeys(
        (config.GEMINI_MODELO, config.GEMINI_MODELO_RESERVA)) if m] if config.GEMINI_API_KEY else []
    groq = [(_Groq, config.GROQ_MODELO)] if config.GROQ_API_KEY else []
    return groq + gemini if config.IA == "groq" else gemini + groq


class Cerebro:
    def __init__(self) -> None:
        self._cadena = _cadena()
        self._historial: list[tuple[str, str]] = []  # lo hablado, para pasarlo entre proveedores
        self._indice = 0
        self._volver_al_principal = 0.0
        self._motor = self._crear(0)

    def _crear(self, indice: int):
        clase, modelo = self._cadena[indice]
        return clase(modelo, self._historial[-MEMORIA_DE_CONVERSACION:])

    @property
    def proveedor(self) -> str:
        return f"{self._motor.nombre} ({self._motor.modelo})"

    def responder_seguro(self, mensaje: str) -> tuple[str, bool]:
        """Responde con el proveedor en uso; si está saturado, salta al siguiente.
        Los fallos vuelven como un aviso legible. Devuelve (texto, es_error)."""
        if self._indice and time.time() > self._volver_al_principal:
            self._indice, self._motor = 0, self._crear(0)
        ultimo = "No pude conectarme al Nexo."
        while True:
            try:
                texto = self._motor.responder(mensaje) or "..."
            except FalloIA as e:
                return str(e), True
            except Saturado as e:
                ultimo = str(e)
                if self._indice + 1 >= len(self._cadena):
                    # Todos saturados: la próxima vez, otra vez desde el principal
                    self._indice, self._motor = 0, self._crear(0)
                    return (f"No pude conectarme al Nexo ({ultimo}). "
                            "Intenta de nuevo en un momento."), True
                self._indice += 1
                self._motor = self._crear(self._indice)
                self._volver_al_principal = time.time() + MINUTOS_EN_RESERVA * 60
                continue
            self._historial += [("user", mensaje), ("assistant", texto)]
            return texto, False
