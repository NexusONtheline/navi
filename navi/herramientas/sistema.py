"""Herramientas de sistema: abrir apps, actualizaciones, estado del PC.

Cada función pública es una herramienta que Gemini puede llamar.
Gemini lee el docstring y los tipos para saber cuándo y cómo usarla,
así que deben estar bien escritos (y en español, porque NAVI habla español).
"""

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from ..escritorio import en_sway

# Solo nombres de programa simples: evita que la IA meta cosas como "firefox; rm -rf ~"
_NOMBRE_APP_VALIDO = re.compile(r"^[A-Za-z0-9._+-]+$")


def abrir_app(app: str, workspace: int | None = None) -> str:
    """Abre una aplicación del sistema, opcionalmente en un workspace de Sway.

    Args:
        app: Nombre del ejecutable, por ejemplo "firefox", "alacritty" o "thunar".
        workspace: Número del workspace donde abrirla. Omitir para usar el actual.
    """
    if not _NOMBRE_APP_VALIDO.match(app):
        return f"Nombre de app no válido: {app!r}"
    if shutil.which(app) is None:
        return f"No encontré '{app}' instalado en el sistema."

    if en_sway():
        comando = f"exec {app}"
        if workspace is not None:
            comando = f"workspace number {int(workspace)}; {comando}"
        resultado = subprocess.run(["swaymsg", comando], capture_output=True, text=True)
        if resultado.returncode != 0:
            return f"Sway rechazó el comando: {resultado.stderr.strip()}"
    else:
        # Fuera de Sway: lanzamos el proceso desligado de NAVI
        subprocess.Popen([app], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    donde = f" en el workspace {workspace}" if workspace is not None else ""
    return f"'{app}' abierto{donde}."


def revisar_actualizaciones() -> str:
    """Revisa cuántos paquetes tienen actualizaciones pendientes (repos oficiales y AUR).
    No instala nada, solo consulta."""
    lineas = []

    if shutil.which("checkupdates"):
        # checkupdates sincroniza en una base temporal: no necesita root y es seguro
        r = subprocess.run(["checkupdates"], capture_output=True, text=True)
        oficiales = r.stdout.split("\n") if r.stdout.strip() else []
        nota = ""
    else:
        r = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True)
        oficiales = r.stdout.split("\n") if r.stdout.strip() else []
        nota = (" (según la última sincronización; instala 'pacman-contrib' "
                "para obtener datos frescos)")
    oficiales = [l for l in oficiales if l.strip()]
    lineas.append(f"Repos oficiales: {len(oficiales)} actualizaciones{nota}.")

    if shutil.which("yay"):
        r = subprocess.run(["yay", "-Qua"], capture_output=True, text=True)
        aur = [l for l in r.stdout.split("\n") if l.strip()]
        lineas.append(f"AUR: {len(aur)} actualizaciones.")
        oficiales += aur

    if oficiales:
        muestra = ", ".join(l.split()[0] for l in oficiales[:10])
        extra = "…" if len(oficiales) > 10 else ""
        lineas.append(f"Algunos paquetes: {muestra}{extra}")
    return "\n".join(lineas)


def estado_sistema() -> str:
    """Devuelve el estado actual del PC: carga de CPU, uso de RAM, temperatura y batería."""
    partes = []

    carga1, _, _ = os.getloadavg()
    partes.append(f"Carga de CPU (1 min): {carga1:.2f} en {os.cpu_count()} núcleos")

    meminfo = {}
    for linea in Path("/proc/meminfo").read_text().splitlines():
        clave, valor = linea.split(":", 1)
        meminfo[clave] = int(valor.split()[0])  # en kB
    total = meminfo["MemTotal"] / 1024 / 1024
    usada = total - meminfo["MemAvailable"] / 1024 / 1024
    partes.append(f"RAM: {usada:.1f} GiB usados de {total:.1f} GiB")

    temps = []
    for zona in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            temps.append(int((zona / "temp").read_text()) / 1000)
        except (OSError, ValueError):
            pass
    if temps:
        partes.append(f"Temperatura máxima: {max(temps):.0f} °C")

    for bat in Path("/sys/class/power_supply").glob("BAT*"):
        try:
            nivel = (bat / "capacity").read_text().strip()
            estado = (bat / "status").read_text().strip()
            partes.append(f"Batería: {nivel}% ({estado})")
        except OSError:
            pass

    return "\n".join(partes)


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_hora() -> str:
    """Devuelve la fecha y hora actuales del sistema."""
    ahora = datetime.now()
    return (f"{_DIAS[ahora.weekday()]} {ahora.day} de {_MESES[ahora.month - 1]} "
            f"de {ahora.year}, {ahora:%H:%M}")


def notificar(titulo: str, mensaje: str) -> str:
    """Muestra una notificación de escritorio.

    Args:
        titulo: Título corto de la notificación.
        mensaje: Texto de la notificación.
    """
    if shutil.which("notify-send") is None:
        return "notify-send no está instalado."
    subprocess.run(["notify-send", "-a", "NAVI", titulo, mensaje])
    return "Notificación enviada."


def _volumen_actual() -> str:
    if shutil.which("wpctl"):
        r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                           capture_output=True, text=True)
        # Formato: "Volume: 0.40" o "Volume: 0.40 [MUTED]"
        partes = r.stdout.split()
        if len(partes) < 2:
            return "No pude leer el volumen."
        silencio = " (silenciado)" if "MUTED" in r.stdout else ""
        return f"Volumen: {round(float(partes[1]) * 100)}%{silencio}"
    volumen = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                             capture_output=True, text=True).stdout
    mudo = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                          capture_output=True, text=True).stdout
    porcentaje = re.search(r"(\d+)%", volumen)
    if not porcentaje:
        return "No pude leer el volumen."
    return f"Volumen: {porcentaje.group(1)}%" + (" (silenciado)" if "yes" in mudo or "sí" in mudo else "")


def volumen(accion: str, cantidad: int = 10) -> str:
    """Controla el volumen de la salida de audio actual (parlantes o audífonos).

    Args:
        accion: "subir", "bajar", "fijar" (pone el volumen exacto en `cantidad`),
            "silenciar", "activar" (quita el silencio) o "consultar".
        cantidad: Porcentaje a subir/bajar, o el volumen exacto si accion es "fijar".
            Máximo 150.
    """
    cantidad = max(0, min(int(cantidad), 150))
    if shutil.which("wpctl"):  # PipeWire
        salida = "@DEFAULT_AUDIO_SINK@"
        comandos = {
            "subir": ["wpctl", "set-volume", "-l", "1.5", salida, f"{cantidad}%+"],
            "bajar": ["wpctl", "set-volume", salida, f"{cantidad}%-"],
            "fijar": ["wpctl", "set-volume", "-l", "1.5", salida, f"{cantidad}%"],
            "silenciar": ["wpctl", "set-mute", salida, "1"],
            "activar": ["wpctl", "set-mute", salida, "0"],
        }
    elif shutil.which("pactl"):  # PulseAudio (o PipeWire sin wpctl)
        salida = "@DEFAULT_SINK@"
        comandos = {
            "subir": ["pactl", "set-sink-volume", salida, f"+{cantidad}%"],
            "bajar": ["pactl", "set-sink-volume", salida, f"-{cantidad}%"],
            "fijar": ["pactl", "set-sink-volume", salida, f"{cantidad}%"],
            "silenciar": ["pactl", "set-sink-mute", salida, "1"],
            "activar": ["pactl", "set-sink-mute", salida, "0"],
        }
    else:
        return "No encontré wpctl ni pactl para controlar el volumen."
    if accion in comandos:
        subprocess.run(comandos[accion], capture_output=True)
    elif accion != "consultar":
        return f"Acción desconocida: {accion}"
    return _volumen_actual()


def modo_privado(activar: bool) -> str:
    """Activa o desactiva el modo privado. En modo privado, el vigilante deja de
    escuchar la frase «NAVI, actívate» y suelta el micrófono por completo.

    Usar SOLO cuando el usuario te lo ordena directamente a ti, con palabras como
    "NAVI, activa el modo privado" o "deja de escucharme". NUNCA la uses solo porque
    se mencione la privacidad, el micrófono o el modo privado en una conversación.
    Ante la duda, pregunta antes de usarla.

    Args:
        activar: True para entrar en modo privado, False para volver a escuchar.
    """
    from .. import senales
    senales.modo_privado(activar)
    if activar:
        notificar("NAVI: modo privado",
                  "Ya no escucho «NAVI, actívate». Para volver: navi --no-privado")
        return "Modo privado activado: ya no escucho «NAVI, actívate» y solté el micrófono."
    return "Modo privado desactivado: vuelvo a escuchar «NAVI, actívate»."


HERRAMIENTAS = [abrir_app, revisar_actualizaciones, estado_sistema, fecha_hora, notificar,
                volumen, modo_privado]
