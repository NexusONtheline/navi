"""Control de ventanas y workspaces de Sway, y brillo de la pantalla.

Las ventanas se eligen por su id interno de Sway (un número): los nombres que
da la IA solo se usan para buscar, nunca se meten en un comando.
"""

import json
import os
import subprocess
from pathlib import Path

from ..escritorio import ancestros, en_sway


def _swaymsg(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["swaymsg", *args], capture_output=True, text=True, timeout=5)


def _ventanas() -> list[dict]:
    """Todas las ventanas, de la usada más recientemente a la más antigua.

    Sway guarda en cada contenedor el orden en que sus hijos tuvieron el foco,
    así que recorrer el árbol siguiendo ese orden da un historial aproximado.
    """
    arbol = json.loads(_swaymsg("-t", "get_tree").stdout)
    lista = []

    def recorrer(nodo: dict, workspace: str | None) -> None:
        if nodo.get("type") == "workspace":
            workspace = nodo["name"]
        hijos = nodo.get("nodes", []) + nodo.get("floating_nodes", [])
        if not hijos and nodo.get("pid") and workspace != "__i3_scratch":
            app = nodo.get("app_id") or (nodo.get("window_properties") or {}).get("class") or ""
            lista.append({"id": nodo["id"], "app": app, "titulo": nodo.get("name") or "",
                          "pid": nodo["pid"], "workspace": workspace,
                          "pantalla_completa": nodo.get("fullscreen_mode", 0) > 0,
                          "flotante": nodo.get("type") == "floating_con",
                          "visible": nodo.get("visible", False), "rect": nodo.get("rect", {})})
        orden = {id_: i for i, id_ in enumerate(nodo.get("focus", []))}
        for hijo in sorted(hijos, key=lambda h: orden.get(h["id"], len(orden))):
            recorrer(hijo, workspace)

    recorrer(arbol, None)
    return lista


def _es_navi(ventana: dict) -> bool:
    return ventana["pid"] in ancestros(os.getpid())


def _buscar(app: str) -> dict | str:
    """La ventana que coincide con `app`; si está vacío, la última usada que no sea NAVI."""
    ventanas = [v for v in _ventanas() if not _es_navi(v)]
    if not ventanas:
        return "No hay otras ventanas abiertas."
    if not app.strip():
        return ventanas[0]
    buscado = app.strip().lower()
    coinciden = [v for v in ventanas
                 if buscado in v["app"].lower() or buscado in v["titulo"].lower()]
    if not coinciden:
        return f"No encontré ninguna ventana de «{app}»."
    return coinciden[0]  # la más reciente de las que coinciden


def _nombre(v: dict) -> str:
    return f"{v['app'] or v['titulo'][:30]} (workspace {v['workspace']})"


def ventanas(accion: str, app: str = "", workspace: int = 0) -> str:
    """Controla las ventanas y workspaces de Sway.

    Si el usuario dice "esta ventana" sin nombrarla, deja `app` vacío: se usa la
    última ventana que tuvo el foco antes de NAVI (nunca la de NAVI).

    Args:
        accion: Una de:
            "listar" (qué ventanas hay abiertas y dónde),
            "enfocar" (ir a una ventana),
            "cerrar" (cerrar una ventana; la app puede pedir guardar cambios),
            "pantalla_completa" (pone la ventana en pantalla completa),
            "quitar_pantalla_completa" (la saca de pantalla completa; sin `app`,
                usa la ventana que esté en pantalla completa),
            "flotante" (alterna entre ventana flotante y en mosaico),
            "mover_a_workspace" (manda la ventana al workspace indicado),
            "ir_a_workspace" (cambia al workspace indicado; no usa `app`).
        app: Nombre de la app o parte del título, por ejemplo "firefox" o "gmail".
        workspace: Número de workspace, para "mover_a_workspace" e "ir_a_workspace".
    """
    if not en_sway():
        return "Controlar ventanas por ahora solo funciona en el escritorio Sway."

    if accion == "listar":
        lista = _ventanas()
        if not lista:
            return "No hay ventanas abiertas."
        return "\n".join(
            f"- {v['app']}: «{v['titulo'][:50]}» en el workspace {v['workspace']}"
            + (" (es NAVI)" if _es_navi(v) else "")
            for v in sorted(lista, key=lambda v: str(v["workspace"])))

    if accion == "ir_a_workspace":
        if workspace < 1:
            return "¿A qué workspace?"
        _swaymsg(f"workspace number {int(workspace)}")
        return f"Ahora estás en el workspace {int(workspace)}."

    if accion == "quitar_pantalla_completa" and not app.strip():
        ventana = next((v for v in _ventanas() if v["pantalla_completa"]), None)
        if ventana is None:
            return "Ninguna ventana está en pantalla completa."
    else:
        ventana = _buscar(app)
    if isinstance(ventana, str):
        return ventana
    criterio = f"[con_id={int(ventana['id'])}]"

    if accion == "enfocar":
        _swaymsg(f"{criterio} focus")
        return f"Enfocada: {_nombre(ventana)}."
    if accion == "cerrar":
        _swaymsg(f"{criterio} kill")
        return f"Cerrada: {_nombre(ventana)}."
    if accion == "pantalla_completa":
        _swaymsg(f"{criterio} focus, fullscreen enable")
        return f"Pantalla completa puesta: {_nombre(ventana)}."
    if accion == "quitar_pantalla_completa":
        _swaymsg(f"{criterio} fullscreen disable")
        return f"Pantalla completa quitada: {_nombre(ventana)}."
    if accion == "flotante":
        _swaymsg(f"{criterio} floating toggle")
        estado = "en mosaico" if ventana["flotante"] else "flotante"
        return f"{_nombre(ventana)} ahora está {estado}."
    if accion == "mover_a_workspace":
        if workspace < 1:
            return "¿A qué workspace la muevo?"
        _swaymsg(f"{criterio} move container to workspace number {int(workspace)}")
        return f"Moví {ventana['app'] or 'la ventana'} al workspace {int(workspace)}."
    return f"Acción desconocida: {accion}"


def _pantalla() -> Path | None:
    return next(iter(sorted(Path("/sys/class/backlight").glob("*"))), None)


def brillo(accion: str, cantidad: int = 10) -> str:
    """Controla el brillo de la pantalla.

    Args:
        accion: "subir", "bajar", "fijar" (pone el brillo exacto en `cantidad`) o "consultar".
        cantidad: Porcentaje a subir o bajar, o el brillo exacto si accion es "fijar".
    """
    pantalla = _pantalla()
    if pantalla is None:
        return "Esta pantalla no permite cambiar el brillo."
    maximo = int((pantalla / "max_brightness").read_text())
    actual = round(int((pantalla / "brightness").read_text()) * 100 / maximo)
    cantidad = max(1, min(int(cantidad), 100))
    nuevo = {"subir": actual + cantidad, "bajar": actual - cantidad,
             "fijar": cantidad}.get(accion)
    if nuevo is None:
        if accion == "consultar":
            return f"Brillo: {actual}%"
        return f"Acción desconocida: {accion}"
    # Nunca por debajo del 5%: con la pantalla negra no podrías ver nada para arreglarlo
    nuevo = max(5, min(nuevo, 100))
    # Los archivos de brillo son de root; logind deja cambiarlo al usuario de la sesión
    r = subprocess.run(
        ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
         "org.freedesktop.login1.Session", "SetBrightness", "ssu",
         "backlight", pantalla.name, str(round(nuevo * maximo / 100))],
        capture_output=True, text=True)
    if r.returncode != 0:
        return f"No pude cambiar el brillo: {r.stderr.strip()}"
    return f"Brillo: {nuevo}%"


HERRAMIENTAS = [ventanas, brillo]
