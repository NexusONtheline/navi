"""NAVI: asistente personal inspirado en Serial Experiments Lain."""

import socket

__version__ = "0.5.0"

# Muchos routers anuncian IPv6 pero no lo enrutan: Python prueba primero cada
# dirección IPv6 y se queda colgado (el navegador no lo nota porque prueba ambas
# a la vez). Probamos IPv4 primero; las redes solo IPv6 siguen funcionando.
_getaddrinfo = socket.getaddrinfo


def _ipv4_primero(*args, **kwargs):
    return sorted(_getaddrinfo(*args, **kwargs), key=lambda d: d[0] != socket.AF_INET)


socket.getaddrinfo = _ipv4_primero
