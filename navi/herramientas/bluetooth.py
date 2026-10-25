"""Herramientas de Bluetooth: ver, conectar, desconectar y emparejar dispositivos.

Usa bluetoothctl (BlueZ). Los nombres que da la IA solo se usan para buscar
entre los dispositivos conocidos; nunca llegan a una shell.
"""

import re
import shutil
import subprocess

_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def _btctl(*args: str, espera: float = 10) -> str:
    try:
        r = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True,
                           timeout=espera)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return r.stdout + r.stderr


def _dispositivos(filtro: str | None = None) -> list[tuple[str, str]]:
    """Lista (mac, nombre). filtro: "Paired", "Connected" o None (todos los conocidos)."""
    salida = _btctl("devices", *([filtro] if filtro else []))
    lista = []
    for linea in salida.splitlines():
        partes = linea.split(" ", 2)
        if len(partes) == 3 and partes[0] == "Device" and _MAC.match(partes[1]):
            lista.append((partes[1], partes[2]))
    return lista


def _info(mac: str) -> dict[str, str]:
    datos = {}
    for linea in _btctl("info", mac).splitlines():
        if ":" in linea:
            clave, valor = linea.strip().split(":", 1)
            datos[clave] = valor.strip()
    return datos


def _buscar(nombre: str, filtro: str | None = "Paired") -> tuple[str, str] | str:
    """Encuentra un dispositivo por nombre (parcial, sin importar mayúsculas)."""
    candidatos = [(m, n) for m, n in _dispositivos(filtro) if nombre.lower() in n.lower()]
    if len(candidatos) == 1:
        return candidatos[0]
    if not candidatos:
        if filtro == "Paired":
            return (f"No hay ningún dispositivo emparejado que se llame '{nombre}'. "
                    "Quizá hay que buscarlo y emparejarlo primero.")
        return f"No encontré '{nombre}' cerca. ¿Está en modo emparejamiento?"
    nombres = ", ".join(n for _, n in candidatos)
    return f"Hay varios que coinciden con '{nombre}': {nombres}. ¿Cuál?"


def _disponible() -> str | None:
    if shutil.which("bluetoothctl") is None:
        return "bluetoothctl no está instalado (paquete bluez-utils)."
    return None


def bluetooth_estado() -> str:
    """Muestra si el Bluetooth está encendido y los dispositivos emparejados,
    indicando cuáles están conectados y su batería si la informan."""
    if error := _disponible():
        return error
    encendido = "Powered: yes" in _btctl("show")
    lineas = [f"Bluetooth {'encendido' if encendido else 'apagado'}."]
    emparejados = _dispositivos("Paired")
    if not emparejados:
        lineas.append("No hay dispositivos emparejados.")
    for mac, nombre in emparejados:
        info = _info(mac)
        estado = "conectado" if info.get("Connected") == "yes" else "desconectado"
        bateria = re.search(r"\((\d+)\)", info.get("Battery Percentage", ""))
        extra = f", batería {bateria.group(1)}%" if bateria else ""
        lineas.append(f"- {nombre}: {estado}{extra}")
    return "\n".join(lineas)


def bluetooth_conectar(dispositivo: str) -> str:
    """Conecta un dispositivo Bluetooth ya emparejado (audífonos, parlante, mouse...).

    Args:
        dispositivo: Nombre o parte del nombre, por ejemplo "TWS" o "parlante".
    """
    if error := _disponible():
        return error
    if "Powered: yes" not in _btctl("show"):
        _btctl("power", "on")
    encontrado = _buscar(dispositivo)
    if isinstance(encontrado, str):
        return encontrado
    mac, nombre = encontrado
    if _info(mac).get("Connected") == "yes":
        return f"{nombre} ya estaba conectado."
    salida = _btctl("connect", mac, espera=20)
    if "Connection successful" in salida or _info(mac).get("Connected") == "yes":
        return f"{nombre} conectado."
    return (f"No pude conectar {nombre}. ¿Está encendido y cerca? "
            "Si está dentro de su estuche, hay que sacarlo.")


def bluetooth_desconectar(dispositivo: str) -> str:
    """Desconecta un dispositivo Bluetooth (sigue emparejado para la próxima vez).

    Args:
        dispositivo: Nombre o parte del nombre del dispositivo.
    """
    if error := _disponible():
        return error
    encontrado = _buscar(dispositivo)
    if isinstance(encontrado, str):
        return encontrado
    mac, nombre = encontrado
    _btctl("disconnect", mac)
    return f"{nombre} desconectado."


def bluetooth_encender(encender: bool) -> str:
    """Enciende o apaga el Bluetooth del PC.

    Args:
        encender: True para encender, False para apagar.
    """
    if error := _disponible():
        return error
    if encender and shutil.which("rfkill"):
        subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
    _btctl("power", "on" if encender else "off")
    encendido = "Powered: yes" in _btctl("show")
    return f"Bluetooth {'encendido' if encendido else 'apagado'}."


def bluetooth_buscar(segundos: int = 8) -> str:
    """Busca dispositivos Bluetooth cercanos que aún no están emparejados.
    El dispositivo debe estar en modo emparejamiento (normalmente con una luz parpadeando).

    Args:
        segundos: Cuánto tiempo buscar, entre 5 y 20.
    """
    if error := _disponible():
        return error
    segundos = max(5, min(int(segundos), 20))
    _btctl("--timeout", str(segundos), "scan", "on", espera=segundos + 5)
    emparejados = {m for m, _ in _dispositivos("Paired")}
    # Los que solo tienen la MAC como nombre suelen ser ruido (celulares de vecinos, etc.)
    nuevos = [n for m, n in _dispositivos()
              if m not in emparejados and n.replace("-", ":") != m]
    if not nuevos:
        return "No encontré dispositivos nuevos cerca."
    return "Encontré: " + ", ".join(nuevos)


def bluetooth_emparejar(dispositivo: str) -> str:
    """Empareja, marca como confiable y conecta un dispositivo nuevo.
    Primero hay que usar bluetooth_buscar para que el PC lo vea.

    Args:
        dispositivo: Nombre o parte del nombre del dispositivo encontrado.
    """
    if error := _disponible():
        return error
    encontrado = _buscar(dispositivo, filtro=None)
    if isinstance(encontrado, str):
        return encontrado
    mac, nombre = encontrado
    salida = _btctl("pair", mac, espera=30)
    if "Pairing successful" not in salida and "AlreadyExists" not in salida:
        return (f"No pude emparejar {nombre}. Si pide un código o confirmación, "
                "hay que hacerlo desde blueman-manager.")
    _btctl("trust", mac)
    _btctl("connect", mac, espera=20)
    return f"{nombre} emparejado y conectado. La próxima vez basta con pedir que lo conecte."


HERRAMIENTAS = [bluetooth_estado, bluetooth_conectar, bluetooth_desconectar,
                bluetooth_encender, bluetooth_buscar, bluetooth_emparejar]
