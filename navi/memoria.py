"""La memoria de NAVI: datos que el usuario le pidió recordar.

Se guarda en ~/.local/share/navi/memoria.json, fuera del proyecto, para que
nunca se suba a GitHub y cada usuario del PC tenga la suya.
"""

import json
import os
import re
from datetime import date
from pathlib import Path

ARCHIVO = (Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
           / "navi" / "memoria.json")
MAXIMO = 200

# Cosas que jamás deben guardarse (y que además viajarían a Gemini)
_SENSIBLE = re.compile(
    r"contraseñ|password|passwd|clave\b|\bpin\b|cvv|código de seguridad|"
    r"\b(?:\d[ -]?){12,19}\b",  # números largos tipo tarjeta o cuenta
    re.IGNORECASE,
)


def cargar() -> list[dict]:
    try:
        return json.loads(ARCHIVO.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _guardar(recuerdos: list[dict]) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    temporal = ARCHIVO.with_suffix(".tmp")
    temporal.write_text(json.dumps(recuerdos, ensure_ascii=False, indent=2))
    temporal.chmod(0o600)
    temporal.replace(ARCHIVO)  # reemplazo atómico: nunca queda a medio escribir


def es_sensible(texto: str) -> bool:
    return bool(_SENSIBLE.search(texto))


def agregar(dato: str) -> None:
    recuerdos = cargar()
    recuerdos.append({"dato": dato, "fecha": date.today().isoformat()})
    _guardar(recuerdos[-MAXIMO:])


def olvidar(texto: str) -> list[str]:
    recuerdos = cargar()
    borrar = [r for r in recuerdos if texto.lower() in r["dato"].lower()]
    if borrar:
        _guardar([r for r in recuerdos if r not in borrar])
    return [r["dato"] for r in borrar]


def como_texto() -> str:
    """Los recuerdos listos para incluir en las instrucciones de NAVI."""
    return "\n".join(f"- {r['dato']} (desde {r['fecha']})" for r in cargar())
