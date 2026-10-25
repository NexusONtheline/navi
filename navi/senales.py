"""Señales entre NAVI y el vigilante de "NAVI, actívate".

Todo vive en una carpeta temporal del usuario que se borra al apagar el PC:
- despertar: tubería (FIFO) por la que el vigilante le dice a NAVI "escucha".
- ocupada:   existe mientras NAVI habla o escucha (el vigilante la ignora).
- privado:   existe en modo privado (el vigilante suelta el micrófono).
"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

CARPETA = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "navi"
TUBERIA = CARPETA / "despertar"
OCUPADA = CARPETA / "ocupada"
PRIVADO = CARPETA / "privado"
PID_NAVI = CARPETA / "navi.pid"


def _preparar() -> None:
    CARPETA.mkdir(mode=0o700, parents=True, exist_ok=True)


def _proceso_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _leer_pid(ruta: Path) -> int | None:
    try:
        return int(ruta.read_text().strip())
    except (OSError, ValueError):
        return None


@contextmanager
def ocupada():
    """Marca a NAVI como ocupada mientras dura el bloque `with`."""
    _preparar()
    OCUPADA.write_text(str(os.getpid()))
    try:
        yield
    finally:
        OCUPADA.unlink(missing_ok=True)


def esta_ocupada() -> bool:
    pid = _leer_pid(OCUPADA)
    if pid is None:
        return False
    if not _proceso_vivo(pid):
        OCUPADA.unlink(missing_ok=True)  # NAVI se cerró a la fuerza mientras hablaba
        return False
    return True


def modo_privado(activar: bool) -> None:
    _preparar()
    if activar:
        PRIVADO.touch()
    else:
        PRIVADO.unlink(missing_ok=True)


def en_modo_privado() -> bool:
    return PRIVADO.exists()


def abrir_tuberia() -> int:
    """Crea la tubería y la abre para leer. Devuelve el descriptor."""
    _preparar()
    TUBERIA.unlink(missing_ok=True)
    os.mkfifo(TUBERIA, 0o600)
    PID_NAVI.write_text(str(os.getpid()))
    fd = os.open(TUBERIA, os.O_RDONLY | os.O_NONBLOCK)
    # Un escritor propio evita que select() se dispare sin parar cuando
    # el vigilante cierra su lado
    os.open(TUBERIA, os.O_WRONLY | os.O_NONBLOCK)
    return fd


def cerrar_tuberia() -> None:
    TUBERIA.unlink(missing_ok=True)
    PID_NAVI.unlink(missing_ok=True)


def pid_navi() -> int | None:
    """PID de la NAVI abierta, o None si no hay ninguna viva."""
    pid = _leer_pid(PID_NAVI)
    return pid if pid is not None and _proceso_vivo(pid) else None


def avisar_a_navi() -> bool:
    """Le dice a la NAVI abierta que escuche. False si no hay ninguna abierta."""
    try:
        fd = os.open(TUBERIA, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:  # no existe, o nadie la está leyendo (NAVI cerrada)
        return False
    try:
        os.write(fd, b"escuchar\n")
    finally:
        os.close(fd)
    return True
