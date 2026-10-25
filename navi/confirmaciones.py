"""Confirmaciones que no pasan por la IA.

Para las acciones delicadas (apagar el PC, capturar la pantalla) la propia
interfaz le pregunta al usuario y espera su respuesta. La IA no puede saltarse
la pregunta ni contestarla por él.
"""

import unicodedata
from collections.abc import Callable

_preguntar: Callable[[str], str] | None = None

_SI = {"si", "dale", "ok", "okay", "vale", "claro", "adelante", "hazlo", "confirmo",
       "afirmativo", "venga", "porfa", "yes", "obvio", "simon", "listo"}
_NO = {"no", "nop", "nel", "cancela", "cancelar", "espera", "mejor", "nunca"}


def registrar(funcion: Callable[[str], str]) -> None:
    """La interfaz registra cómo preguntarle al usuario y leer su respuesta."""
    global _preguntar
    _preguntar = funcion


def _palabras(texto: str) -> set[str]:
    sin_tildes = unicodedata.normalize("NFD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return set("".join(c if c.isalnum() else " " for c in sin_tildes).split())


def es_afirmativo(respuesta: str) -> bool:
    palabras = _palabras(respuesta)
    return bool(palabras & _SI) and not palabras & _NO


def preguntar(pregunta: str) -> bool:
    """Pregunta directamente al usuario. Sin interfaz (o ante cualquier fallo): no."""
    if _preguntar is None:
        return False
    try:
        return es_afirmativo(_preguntar(pregunta))
    except Exception:
        return False
