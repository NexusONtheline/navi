"""Diferencias entre escritorios: Sway (Wayland) y los clásicos en X11 (Cinnamon, XFCE...).

Todo lo que dependa de cómo se abren terminales o se enfocan ventanas pasa por aquí.
"""

import os
import shutil
import subprocess


def en_sway() -> bool:
    return bool(os.environ.get("SWAYSOCK")) and shutil.which("swaymsg") is not None


def en_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _comando_terminal(clase: str, titulo: str, programa: list[str]) -> list[str] | None:
    """Cómo abrir `programa` en una ventana de terminal nueva con la terminal que haya."""
    if shutil.which("alacritty"):
        return ["alacritty", "--class", clase, "--title", titulo, "-e", *programa]
    if shutil.which("gnome-terminal"):  # Linux Mint, Ubuntu...
        return ["gnome-terminal", f"--title={titulo}", "--", *programa]
    if shutil.which("kitty"):
        return ["kitty", "--class", clase, "--title", titulo, *programa]
    if shutil.which("konsole"):
        return ["konsole", "-p", f"tabtitle={titulo}", "-e", *programa]
    if shutil.which("xfce4-terminal"):
        return ["xfce4-terminal", f"--title={titulo}", "-x", *programa]
    if shutil.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *programa]
    return None


def abrir_en_terminal(programa: list[str], clase: str = "navi", titulo: str = "NAVI") -> bool:
    """Abre `programa` en una ventana de terminal propia. False si no hay terminal."""
    comando = _comando_terminal(clase, titulo, programa)
    if comando is None:
        return False
    if en_sway():
        # Con swaymsg la ventana hereda el entorno de Sway (y sus reglas de ventana)
        r = subprocess.run(["swaymsg", "exec", subprocess.list2cmdline(comando)],
                           capture_output=True)
        return r.returncode == 0
    subprocess.Popen(comando, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def ancestros(pid: int) -> list[int]:
    """El proceso y todos sus padres (NAVI → bash → terminal → ...)."""
    cadena = []
    while pid > 1 and len(cadena) < 20:
        cadena.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                estado = f.read()
        except OSError:
            break
        pid = int(estado.rsplit(")", 1)[1].split()[1])  # campo ppid
    return cadena


def traer_ventana(pid: int) -> bool:
    """Enfoca la ventana donde corre ese proceso (aunque esté en otro escritorio)."""
    cadena = ancestros(pid)
    if en_sway():
        for candidato in cadena:
            r = subprocess.run(["swaymsg", f"[pid={candidato}] focus"],
                               capture_output=True, text=True)
            if r.returncode == 0 and '"success": true' in r.stdout:
                return True
        return False
    if shutil.which("wmctrl"):  # X11: wmctrl -lp lista ventanas con su pid
        listado = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True).stdout
        for linea in listado.splitlines():
            partes = linea.split(None, 3)
            if len(partes) >= 3 and partes[2].isdigit() and int(partes[2]) in cadena:
                subprocess.run(["wmctrl", "-i", "-a", partes[0]], capture_output=True)
                return True
    return False
