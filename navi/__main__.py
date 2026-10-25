"""Punto de entrada: python -m navi [--escuchar | --despertar | --privado | --no-privado]"""

import signal
import sys

from google.genai import errors

from . import config, confirmaciones, interfaz, senales
from .cerebro import ERRORES_DE_RED, Cerebro
from .oido import Oido
from .voz import Voz

SALIDAS = {"salir", "exit", "quit", "adios", "adiós"}

AYUDA = """Uso: navi [opción]

  (sin opción)   abre NAVI
  --escuchar     abre NAVI y empieza a escucharte de inmediato
  --abrir        abre NAVI en una ventana de terminal nueva (para atajos)
  --despertar    inicia el vigilante de «NAVI, actívate»
  --saludo       NAVI te saluda (hora, clima, recordatorios de hoy)
  --privado      modo privado: el vigilante suelta el micrófono
  --no-privado   el vigilante vuelve a escuchar
"""


def escuchar(oido: Oido) -> str:
    """Graba del micrófono y devuelve lo que dijiste."""
    try:
        with senales.ocupada(), interfaz.escuchando():
            audio = oido.escuchar()
        with interfaz.transcribiendo():
            texto = oido.transcribir(audio)
    except KeyboardInterrupt:
        interfaz.error("Escucha cancelada.")
        return ""
    if not texto:
        interfaz.error(oido.problema or "No te escuché. Presiona Enter e intenta de nuevo.")
        return ""
    interfaz.mostrar_dictado(texto)
    return texto


def responder(cerebro: Cerebro, voz: Voz, mensaje: str) -> None:
    try:
        with interfaz.pensando():
            respuesta = cerebro.responder(mensaje)
        interfaz.decir(respuesta)
        voz.decir(respuesta)
    except errors.ClientError as e:
        if e.code == 429:
            interfaz.error("Límite gratuito de Gemini alcanzado. Espera un poco e intenta de nuevo.")
        elif e.code in (400, 403) and "API key" in str(e):
            interfaz.error("La API key no es válida. Revisa tu archivo .env.")
        elif e.code == 404:
            interfaz.error(f"El modelo '{config.GEMINI_MODELO}' no existe. Cambia GEMINI_MODELO en .env.")
        else:
            interfaz.error(f"Gemini respondió con un error: {e}")
    except errors.ServerError:
        interfaz.error("Los servidores de Gemini están saturados. Intenta en un momento.")
    except ERRORES_DE_RED:  # sin internet o Gemini no contesta
        interfaz.error("No pude conectarme al Nexo: Gemini no respondió. Intenta de nuevo.")
        cerebro.reconectar()
    except KeyboardInterrupt:
        interfaz.error("Interrumpido.")


def conversar(escuchar_al_abrir: bool = False, buenos_dias: bool = False) -> None:
    config.validar()
    # Cerrar la ventana con la X manda SIGHUP: salimos limpiando las señales
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    oido = Oido()
    interfaz.arranque(con_oido=oido.disponible)
    cerebro = Cerebro()
    voz = Voz()
    tuberia = senales.abrir_tuberia()
    por_voz = escuchar_al_abrir  # si el último mensaje fue hablado, las preguntas también

    def preguntar(pregunta: str) -> str:
        """Le pregunta al usuario directamente (sin pasar por la IA)."""
        with interfaz.pausar_estado():
            interfaz.decir(pregunta)
            if voz.activa:
                voz.decir(pregunta)
                voz.esperar()
            if por_voz and oido.disponible:
                return escuchar(oido)
            interfaz.pista("responde sí o no (Enter vacío para decirlo en voz alta)")
            respuesta = interfaz.pedir_mensaje()
            if not respuesta and oido.disponible:
                respuesta = escuchar(oido)
            return respuesta or ""

    confirmaciones.registrar(preguntar)

    if buenos_dias:
        from .saludo import _datos, pedido_de_saludo
        with interfaz.pensando():
            pedido = pedido_de_saludo(_datos())
        responder(cerebro, voz, pedido)
        voz.esperar()  # que termine de hablar antes de escucharte
        escuchar_al_abrir = por_voz = True

    try:
        pendiente_escuchar = escuchar_al_abrir
        while True:
            if pendiente_escuchar:
                mensaje = ""
                pendiente_escuchar = False
            else:
                try:
                    mensaje = interfaz.pedir_mensaje(tuberia)
                except (KeyboardInterrupt, EOFError):
                    mensaje = "salir"
                if mensaje is None:  # «NAVI, actívate» con la ventana abierta
                    mensaje = ""

            voz.callar()
            por_voz = not mensaje
            if not mensaje:
                if not oido.disponible:
                    continue
                mensaje = escuchar(oido)
                if not mensaje:
                    continue

            if mensaje.lower().strip(" .!¡") in SALIDAS:
                despedida = "Desconectando. Recuerda: todos estamos conectados."
                interfaz.decir(despedida)
                if voz.activa:
                    voz.decir(despedida)
                    voz.esperar()
                break
            if mensaje.lower() in ("/voz", "silencio"):
                voz.activa_usuario = not voz.activa_usuario
                interfaz.decir("Voz activada." if voz.activa_usuario else "Me quedo en silencio.")
                continue

            responder(cerebro, voz, mensaje)
    finally:
        senales.cerrar_tuberia()


def main() -> None:
    opcion = sys.argv[1] if len(sys.argv) > 1 else ""
    if opcion == "--despertar":
        from . import despertar
        despertar.main()
    elif opcion == "--brillo" and len(sys.argv) > 3:
        from .herramientas.ventanas import brillo
        brillo(sys.argv[2], int(sys.argv[3]))
    elif opcion == "--abrir":  # para atajos de teclado: NAVI en su propia ventana
        from . import escritorio
        escritorio.abrir_en_terminal([str(config.RAIZ / "navi.sh")])
    elif opcion == "--saludo":
        from .saludo import saludar
        saludar()
    elif opcion == "--cola":
        from .herramientas.musica import procesar_cola
        procesar_cola()
    elif opcion == "--avisar" and len(sys.argv) > 2:
        from .avisos import avisar
        avisar(" ".join(sys.argv[2:]))
    elif opcion == "--privado":
        senales.modo_privado(True)
        print("Modo privado: el vigilante soltó el micrófono.")
    elif opcion == "--no-privado":
        senales.modo_privado(False)
        print("El vigilante vuelve a escuchar «NAVI, actívate».")
    elif opcion in ("", "--escuchar", "--buenos-dias"):
        conversar(escuchar_al_abrir=opcion == "--escuchar", buenos_dias=opcion == "--buenos-dias")
    else:
        print(AYUDA)


if __name__ == "__main__":
    main()
