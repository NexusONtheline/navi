"""Lo que pasa cuando suena un recordatorio: `navi --avisar "mensaje"`.

Lo lanza systemd a la hora programada, así que funciona aunque NAVI esté cerrada.
"""

import shutil
import subprocess

from . import config


def avisar(mensaje: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "NAVI", "-u", "critical",
                        "NAVI: recordatorio", mensaje])

    from .despertar import _sonar_pitido
    _sonar_pitido()

    from .voz import Voz
    voz = Voz()
    if voz.activa:
        saludo = f"{config.NOMBRE_USUARIO}, te" if config.NOMBRE_USUARIO else "Te"
        voz.decir(f"{saludo} recuerdo: {mensaje}")
        voz.esperar()
