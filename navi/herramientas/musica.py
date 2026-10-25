"""Música: controlar cualquier reproductor (playerctl) y poner canciones de YouTube (mpv).

playerctl habla con todo lo que soporte MPRIS: Spotify, Firefox, kew, mpv...
Para YouTube usamos mpv + yt-dlp en modo solo audio, sin abrir el navegador.
"""

import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

from .. import config, senales

_PID_MUSICA = senales.CARPETA / "musica.pid"
_PID_COLA = senales.CARPETA / "musica-cola.pid"
_COLA = senales.CARPETA / "musica-cola.json"
_SOCKET = senales.CARPETA / "musica.sock"


def _playerctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["playerctl", *args], capture_output=True, text=True, timeout=5)


def _elegir_reproductor() -> str | None:
    """El que está sonando; si ninguno suena, el que está en pausa; si no, el primero."""
    jugadores = _playerctl("-l").stdout.split()
    if not jugadores:
        return None
    estados = {j: _playerctl("-p", j, "status").stdout.strip() for j in jugadores}
    for buscado in ("Playing", "Paused"):
        for j, estado in estados.items():
            if estado == buscado:
                return j
    return jugadores[0]


def _describir(jugador: str) -> str:
    # Separador invisible: los títulos de YouTube suelen traer "|"
    r = _playerctl("-p", jugador, "metadata", "--format",
                   "{{artist}}\x1f{{title}}\x1f{{status}}")
    artista, titulo, estado = (r.stdout.rstrip("\n").split("\x1f") + ["", "", ""])[:3]
    if not titulo:
        return f"{jugador} no informa qué está sonando."
    estado = {"Playing": "sonando", "Paused": "en pausa"}.get(estado, estado.lower())
    nombre = f"{artista} - {titulo}" if artista else titulo
    return f"{nombre} ({estado}, en {jugador.split('.')[0]})"


def controlar_musica(accion: str) -> str:
    """Controla la música que esté sonando en cualquier reproductor
    (Spotify, Firefox/YouTube, kew, la música que puso NAVI, etc.).

    Args:
        accion: "pausar", "reanudar", "siguiente", "anterior" o "detener".
    """
    if shutil.which("playerctl") is None:
        return "playerctl no está instalado."
    comandos = {"pausar": "pause", "reanudar": "play", "siguiente": "next",
                "anterior": "previous", "detener": "stop"}
    if accion not in comandos:
        return f"Acción desconocida: {accion}"
    if accion == "pausar":
        _playerctl("-a", "pause")  # que se callen todos
        return "Música en pausa."
    jugador = _elegir_reproductor()
    if jugador is None:
        return "No hay ningún reproductor de música abierto."
    _playerctl("-p", jugador, comandos[accion])
    if accion == "detener" and jugador.startswith("mpv"):
        _detener_musica_navi()
        return "Música detenida."
    return {"reanudar": "Reanudando.", "siguiente": "Siguiente canción.",
            "anterior": "Canción anterior.", "detener": "Música detenida."}[accion]


def que_suena() -> str:
    """Dice qué canción está sonando ahora mismo y en qué reproductor."""
    if shutil.which("playerctl") is None:
        return "playerctl no está instalado."
    jugador = _elegir_reproductor()
    if jugador is None:
        return "No suena nada: no hay ningún reproductor abierto."
    return _describir(jugador)


def _detener_musica_navi() -> None:
    for archivo in (_PID_MUSICA, _PID_COLA):
        try:
            os.kill(int(archivo.read_text()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        archivo.unlink(missing_ok=True)
    _SOCKET.unlink(missing_ok=True)


# ---------- YouTube ----------
# mpv puede buscar en YouTube por su cuenta, pero pide muchas cosas de más
# (subtítulos en todos los idiomas...) y YouTube responde "demasiadas peticiones".
# Así que le pedimos a yt-dlp solo lo justo y le damos a mpv el audio ya listo.

def _ytdlp() -> list[str]:
    # El yt-dlp instalado con NAVI (pip) está al día; el de apt suele ser viejo y YouTube lo bloquea
    base = ([sys.executable, "-m", "yt_dlp"] if importlib.util.find_spec("yt_dlp")
            else ["yt-dlp"])
    args = [*base, "--no-warnings"]
    if config.YOUTUBE_CLIENTE:
        args += ["--extractor-args", f"youtube:player_client={config.YOUTUBE_CLIENTE}"]
    if config.YOUTUBE_COOKIES:
        args += ["--cookies-from-browser", config.YOUTUBE_COOKIES]
    return args


def _buscar_youtube(busqueda: str, cantidad: int) -> list[tuple[str, str]]:
    """[(id, título)] de los primeros resultados. Una sola petición, rápida."""
    try:
        r = subprocess.run([*_ytdlp(), "--flat-playlist", "--print", "%(id)s\t%(title)s",
                            f"ytsearch{cantidad}:{busqueda}"],
                           capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired:
        return []
    return [tuple(l.split("\t", 1)) for l in r.stdout.splitlines() if "\t" in l]


def _url_audio(video: str) -> str | None:
    """Dirección directa del audio de un video (caduca en unas horas)."""
    for _ in range(2):  # YouTube falla al azar de vez en cuando
        try:
            r = subprocess.run([*_ytdlp(), "--no-playlist", "-f", "bestaudio/best",
                                "--print", "urls", f"https://www.youtube.com/watch?v={video}"],
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            continue
        url = next((l for l in r.stdout.splitlines() if l.startswith("http")), None)
        if url:
            return url
    return None


def _titulo_mpv(titulo: str) -> str:
    # %largo% le dice a mpv cuántos bytes ocupa: así las comas del título no rompen nada
    return f"force-media-title=%{len(titulo.encode())}%{titulo}"


def _mpv_ipc(comando: list) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(str(_SOCKET))
            s.sendall((json.dumps({"command": comando}) + "\n").encode())
        return True
    except OSError:
        return False


def procesar_cola() -> None:
    """Ayudante en segundo plano (navi --cola): prepara las siguientes canciones
    y se las va pasando a mpv mientras suena la primera."""
    try:
        pendientes = json.loads(_COLA.read_text())
    except (OSError, json.JSONDecodeError):
        return
    for video, titulo in pendientes:
        url = _url_audio(video)
        if url and not _mpv_ipc(["loadfile", url, "append", -1, _titulo_mpv(titulo)]):
            return  # mpv se cerró: ya no hay a quién pasarle canciones
    _PID_COLA.unlink(missing_ok=True)


def poner_musica(busqueda: str, canciones: int = 1) -> str:
    """Busca en YouTube y reproduce el audio en segundo plano, sin abrir el navegador.
    Reemplaza la música que NAVI hubiera puesto antes. Tarda unos segundos en sonar.

    Args:
        busqueda: Canción, artista o estilo, por ejemplo "Duvet Bôa" o "lofi para estudiar".
        canciones: Cuántos resultados poner en cola, de 1 a 10. Usa 1 para una canción
            concreta y 5 o más para "pon música de..." o un estilo.
    """
    if shutil.which("mpv") is None:
        return "Necesito mpv instalado para poner música."
    if not importlib.util.find_spec("yt_dlp") and shutil.which("yt-dlp") is None:
        return "Necesito yt-dlp instalado para buscar en YouTube."
    busqueda = " ".join(busqueda.split())[:150]
    if not busqueda:
        return "¿Qué quieres escuchar?"
    canciones = max(1, min(int(canciones), 10))

    _detener_musica_navi()
    senales.CARPETA.mkdir(mode=0o700, parents=True, exist_ok=True)
    resultados = _buscar_youtube(busqueda, canciones)
    if not resultados:
        return f"No encontré «{busqueda}» en YouTube (o YouTube no respondió)."

    # Probamos los resultados en orden hasta que uno suene de verdad
    for posicion, (video, titulo) in enumerate(resultados[:3]):
        url = _url_audio(video)
        if url is None:
            continue
        _playerctl("-a", "pause")  # que no se mezcle con lo que sonara antes
        proceso = subprocess.Popen(
            ["mpv", "--no-video", "--no-terminal", *config.MPV_EXTRA,
             f"--input-ipc-server={_SOCKET}", f"--force-media-title={titulo}", url],
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _PID_MUSICA.write_text(str(proceso.pid))
        if not _esperar_que_suene(proceso):
            proceso.terminate()
            continue

        siguientes = resultados[posicion + 1:]
        if siguientes:
            _COLA.write_text(json.dumps(siguientes, ensure_ascii=False))
            ayudante = subprocess.Popen(
                [sys.executable, "-m", "navi", "--cola"], cwd=config.RAIZ,
                start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _PID_COLA.write_text(str(ayudante.pid))
            return f"Sonando: {titulo} (y {len(siguientes)} más en camino)."
        return f"Sonando: {titulo}."

    _detener_musica_navi()
    return ("YouTube no me dejó reproducirlo ahora mismo (a veces se pone estricto "
            "si se le pide mucho seguido). Intenta de nuevo en un rato.")


def _esperar_que_suene(proceso: subprocess.Popen) -> bool:
    """Espera a que la canción de verdad avance, para no mentirle al usuario."""
    for _ in range(40):  # hasta ~20 s
        time.sleep(0.5)
        if proceso.poll() is not None:
            return False
        for jugador in _playerctl("-l").stdout.split():
            if not jugador.startswith("mpv"):
                continue
            try:
                posicion = float(_playerctl("-p", jugador, "position").stdout.strip() or 0)
            except ValueError:
                continue
            if posicion > 0.3 and _playerctl("-p", jugador, "status").stdout.strip() == "Playing":
                return True
    return False


HERRAMIENTAS = [controlar_musica, que_suena, poner_musica]
