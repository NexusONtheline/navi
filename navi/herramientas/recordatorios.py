"""Recordatorios y temporizadores con los temporizadores de systemd.

No hace falta tener NAVI abierta: systemd ejecuta `navi --avisar "..."` a la
hora indicada, que muestra una notificación y lo dice en voz alta.
Se pierden si apagas el PC antes de que suenen.
"""

import json
import secrets
import shutil
import subprocess
from datetime import datetime, timedelta

from .. import config

_PREFIJO = "navi-rec-"


def _systemd_disponible() -> str | None:
    if shutil.which("systemd-run") is None:
        return "Este sistema no tiene systemd, así que no puedo programar avisos."
    return None


def _programar(mensaje: str, cuando: list[str]) -> str:
    unidad = _PREFIJO + secrets.token_hex(3)
    r = subprocess.run(
        ["systemd-run", "--user", f"--unit={unidad}", f"--description=NAVI: {mensaje}",
         "--timer-property=AccuracySec=1s", *cuando,
         str(config.RAIZ / "navi.sh"), "--avisar", mensaje],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return f"No pude programarlo: {r.stderr.strip()}"
    return ""


def _legible(momento: datetime) -> str:
    hoy = datetime.now().date()
    if momento.date() == hoy:
        dia = "hoy"
    elif momento.date() == hoy + timedelta(days=1):
        dia = "mañana"
    else:
        dia = momento.strftime("%d/%m")
    return f"{dia} a las {momento:%H:%M}"


def crear_recordatorio(mensaje: str, en_minutos: float = 0, hora: str = "",
                       fecha: str = "") -> str:
    """Programa un recordatorio o temporizador. Cuando llega el momento, NAVI muestra
    una notificación y lo dice en voz alta, aunque esté cerrada.

    Usa `en_minutos` SOLO para tiempos relativos ("en 20 minutos", "temporizador de 1 hora").
    Si el usuario menciona una hora del reloj ("a las 9", "a las 18:30", "mañana a las 8"),
    usa SIEMPRE `hora` (y `fecha` si no es hoy); nunca la conviertas a minutos.
    "Mañana a las 9" → hora="09:00" y fecha = la de mañana (consulta fecha_hora si no la sabes).
    Sin indicación de tarde o noche, "a las 9" significa 09:00.

    Args:
        mensaje: Qué recordar, por ejemplo "sacar la ropa de la lavadora".
            Para un temporizador, algo como "terminó tu temporizador de 10 minutos".
        en_minutos: Dentro de cuántos minutos avisar (puede tener decimales).
        hora: Hora exacta en formato HH:MM de 24 horas. Si ya pasó hoy, será mañana.
        fecha: Fecha en formato AAAA-MM-DD, solo si no es hoy ni mañana.
    """
    if error := _systemd_disponible():
        return error
    mensaje = " ".join(mensaje.split())[:200]
    if not mensaje:
        return "Necesito saber qué recordar."

    if en_minutos and en_minutos > 0:
        segundos = max(1, round(en_minutos * 60))
        momento = datetime.now() + timedelta(seconds=segundos)
        cuando = [f"--on-active={segundos}s"]
    elif hora:
        try:
            hh, mm = (int(x) for x in hora.strip().split(":")[:2])
            dia = datetime.strptime(fecha, "%Y-%m-%d").date() if fecha else datetime.now().date()
            momento = datetime.combine(dia, datetime.min.time()).replace(hour=hh, minute=mm)
        except ValueError:
            return f"No entendí la hora '{hora}' o la fecha '{fecha}'."
        if momento <= datetime.now():
            if fecha:
                return "Esa fecha y hora ya pasaron."
            momento += timedelta(days=1)
        cuando = [f"--on-calendar={momento:%Y-%m-%d %H:%M:00}"]
    else:
        return "Necesito saber cuándo: en cuántos minutos o a qué hora."

    if error := _programar(mensaje, cuando):
        return error
    return f"Listo: te recordaré «{mensaje}» {_legible(momento)}."


def _pendientes() -> list[tuple[str, datetime, str]]:
    r = subprocess.run(["systemctl", "--user", "list-timers", f"{_PREFIJO}*",
                        "--all", "--output=json"], capture_output=True, text=True)
    try:
        temporizadores = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return []
    lista = []
    for t in temporizadores:
        if not t.get("next"):
            continue
        unidad = t["unit"]
        descripcion = subprocess.run(
            ["systemctl", "--user", "show", unidad, "-p", "Description", "--value"],
            capture_output=True, text=True).stdout.strip()
        lista.append((unidad, datetime.fromtimestamp(t["next"] / 1_000_000),
                      descripcion.removeprefix("NAVI: ")))
    return sorted(lista, key=lambda x: x[1])


def ver_recordatorios() -> str:
    """Lista los recordatorios y temporizadores pendientes."""
    if error := _systemd_disponible():
        return error
    pendientes = _pendientes()
    if not pendientes:
        return "No hay recordatorios pendientes."
    return "\n".join(f"- {_legible(momento)}: {mensaje}"
                     for _, momento, mensaje in pendientes)


def cancelar_recordatorio(texto: str) -> str:
    """Cancela recordatorios pendientes cuyo mensaje contenga el texto indicado.

    Args:
        texto: Parte del mensaje del recordatorio, por ejemplo "ropa".
            Usa "todos" para cancelarlos todos.
    """
    if error := _systemd_disponible():
        return error
    pendientes = _pendientes()
    elegidos = [p for p in pendientes
                if texto.strip().lower() == "todos" or texto.lower() in p[2].lower()]
    if not elegidos:
        return f"No encontré ningún recordatorio con «{texto}»."
    for unidad, _, _ in elegidos:
        subprocess.run(["systemctl", "--user", "stop", unidad], capture_output=True)
    return "Cancelado: " + "; ".join(m for _, _, m in elegidos)


HERRAMIENTAS = [crear_recordatorio, ver_recordatorios, cancelar_recordatorio]
