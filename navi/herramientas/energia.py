"""Apagar, reiniciar y suspender el PC, siempre con confirmación del usuario.

La confirmación no pasa por la IA: la interfaz de NAVI le pregunta
directamente al usuario y solo ejecuta si responde que sí.
"""

import subprocess

from .. import confirmaciones

_ACCIONES = {
    "apagar": ("poweroff", "apagar el PC"),
    "reiniciar": ("reboot", "reiniciar el PC"),
    "suspender": ("suspend", "suspender el PC"),
}


def _ejecutar(comando: str, en_minutos: float) -> None:
    if en_minutos > 0:
        segundos = round(en_minutos * 60)
        subprocess.run(["systemd-run", "--user", "--unit=navi-energia",
                        f"--description=NAVI: {comando}", f"--on-active={segundos}s",
                        "systemctl", comando], capture_output=True)
    else:
        subprocess.Popen(["systemctl", comando], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def energia(accion: str, en_minutos: float = 0) -> str:
    """Apaga, reinicia o suspende el PC, ahora o dentro de un rato.
    Llámala directamente: NAVI le preguntará al usuario si está seguro antes de hacerlo.

    Args:
        accion: "apagar", "reiniciar", "suspender", o "cancelar" para anular un
            apagado programado.
        en_minutos: Para programarlo ("apágate en 30 minutos"). 0 = ahora.
    """
    if accion == "cancelar":
        r = subprocess.run(["systemctl", "--user", "stop", "navi-energia.timer"],
                           capture_output=True)
        if r.returncode == 0:
            return "Cancelé el apagado programado."
        return "No había nada programado."

    if accion not in _ACCIONES:
        return f"Acción desconocida: {accion}"
    comando, descripcion = _ACCIONES[accion]
    en_minutos = max(0.0, float(en_minutos))
    cuando = f" dentro de {en_minutos:g} minutos" if en_minutos else " ahora"

    if not confirmaciones.preguntar(f"¿Seguro que quieres {descripcion}{cuando}? "
                                    "Lo que no hayas guardado se perderá."):
        return ("Respondió que no, así que no hice nada. Contéstale de tú, en una frase "
                f"y sin volver a preguntar, algo como: «Vale, no voy a {descripcion}.»")

    _ejecutar(comando, en_minutos)
    if en_minutos:
        return (f"Hecho (ya lo confirmó): voy a {descripcion} dentro de {en_minutos:g} "
                "minutos. Despídete o confírmalo en una frase, sin volver a preguntar.")
    return (f"Hecho (ya lo confirmó): voy a {descripcion} ahora. "
            "Despídete en una frase corta, sin volver a preguntar.")


HERRAMIENTAS = [energia]
