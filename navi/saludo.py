"""El saludo al encender el PC: `navi --saludo` (Sway lo lanza al iniciar sesión).

Abre la ventana de NAVI, que saluda (hora, clima, recordatorios de hoy) y
se queda escuchando. Si no hay ninguna terminal, saluda en voz alta con una
notificación.
"""

import shutil
import subprocess
import time
from datetime import datetime

from . import config, escritorio
from .herramientas.clima import clima
from .herramientas.recordatorios import _pendientes
from .herramientas.sistema import fecha_hora, revisar_actualizaciones


def _momento_del_dia(hora: int) -> str:
    if 5 <= hora < 12:
        return "Buenos días"
    if 12 <= hora < 19:
        return "Buenas tardes"
    return "Buenas noches"


def _recordatorios_de_hoy() -> list[str]:
    hoy = datetime.now().date()
    return [f"{momento:%H:%M} {mensaje}" for _, momento, mensaje in _pendientes()
            if momento.date() == hoy]


def _datos() -> dict:
    datos = {"fecha": fecha_hora(), "recordatorios": _recordatorios_de_hoy()}
    if config.CIUDAD:
        # Al iniciar sesión el wifi puede tardar en conectarse
        for _ in range(6):
            resultado = clima()
            if not resultado.startswith("No pude conectarme"):
                datos["clima"] = resultado
                break
            time.sleep(5)
    datos["actualizaciones"] = revisar_actualizaciones()
    return datos


def _saludo_simple(datos: dict) -> str:
    nombre = f", {config.NOMBRE_USUARIO}" if config.NOMBRE_USUARIO else ""
    texto = f"{_momento_del_dia(datetime.now().hour)}{nombre}. Son las {datetime.now():%H:%M}."
    if datos["recordatorios"]:
        texto += f" Hoy tienes {len(datos['recordatorios'])} recordatorios."
    return texto


def pedido_de_saludo(datos: dict) -> str:
    nombre = config.NOMBRE_USUARIO or "tu usuario"
    pedido = (
        f"(Mensaje del sistema: {nombre} acaba de encender el PC.) Salúdale con "
        f"«{_momento_del_dia(datetime.now().hour)}» y cuéntale en 2 o 3 frases cortas: la "
        "hora, el clima de hoy (temperatura y si va a llover; si llueve, sugiere algo "
        "útil), y solo si los hay, sus recordatorios de hoy y si hay muchas "
        "actualizaciones pendientes. Nada de listas ni datos de más."
    )
    return pedido + "\n\nDatos:\n" + "\n".join(
        f"- {clave}: {valor}" for clave, valor in datos.items() if valor)


def _saludo_con_gemini(datos: dict) -> str:
    from google import genai
    from google.genai import types

    from .cerebro import PERSONALIDAD
    pedido = pedido_de_saludo(datos)
    cliente = genai.Client(api_key=config.GEMINI_API_KEY)
    respuesta = cliente.models.generate_content(
        model=config.GEMINI_MODELO, contents=pedido,
        config=types.GenerateContentConfig(system_instruction=PERSONALIDAD))
    return (respuesta.text or "").strip()


def saludar(espera_inicial: float = 8) -> None:
    time.sleep(espera_inicial)  # que terminen de conectarse el wifi y los audífonos
    if escritorio.abrir_en_terminal([str(config.RAIZ / "navi.sh"), "--buenos-dias"]):
        return
    saludar_sin_ventana()


def saludar_sin_ventana() -> None:
    """Saludo en voz alta + notificación, sin abrir NAVI."""
    datos = _datos()
    try:
        texto = _saludo_con_gemini(datos) if config.GEMINI_API_KEY else ""
    except Exception:  # sin internet o sin cuota: saludo sencillo
        texto = ""
    texto = texto or _saludo_simple(datos)
    print(texto, flush=True)

    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "NAVI", "NAVI", texto])
    from .voz import Voz
    voz = Voz()
    if voz.activa:
        voz.decir(texto)
        voz.esperar()
