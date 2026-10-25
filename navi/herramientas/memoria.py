"""Herramientas de memoria: recordar, ver y olvidar datos del usuario."""

from .. import memoria


def recordar(dato: str) -> str:
    """Guarda un dato sobre el usuario o su vida para recordarlo en el futuro,
    incluso en otras conversaciones.

    Úsala SOLO cuando el usuario te pida explícitamente recordar algo
    ("recuerda que...", "no olvides que...", "apúntate que..."). No guardes cosas
    por tu cuenta. Nunca guardes contraseñas, PINs ni datos bancarios.

    Args:
        dato: El dato en una frase clara y en tercera persona, con contexto,
            por ejemplo "Su hermano se llama Pablo" o "Le gusta el ramen picante".
    """
    dato = " ".join(dato.split())[:300]
    if not dato:
        return "No hay nada que recordar."
    if memoria.es_sensible(dato):
        return ("No lo guardé: parece una contraseña, un PIN o un dato bancario. "
                "Eso debe quedarse en un gestor de contraseñas, no en mi memoria.")
    if any(r["dato"].lower() == dato.lower() for r in memoria.cargar()):
        return "Eso ya lo sabía."
    memoria.agregar(dato)
    return f"Guardado en mi memoria: {dato}"


def ver_memoria() -> str:
    """Muestra todo lo que NAVI recuerda del usuario."""
    texto = memoria.como_texto()
    return texto or "Mi memoria está vacía."


def olvidar(texto: str) -> str:
    """Borra de la memoria los datos que contengan el texto indicado.

    Args:
        texto: Parte del dato a olvidar, por ejemplo "ramen" o "hermano".
    """
    borrados = memoria.olvidar(texto)
    if not borrados:
        return f"No encontré nada sobre «{texto}» en mi memoria."
    return "Olvidado: " + "; ".join(borrados)


HERRAMIENTAS = [recordar, ver_memoria, olvidar]
