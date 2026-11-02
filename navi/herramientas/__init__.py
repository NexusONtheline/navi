"""Registro de herramientas de NAVI.

Para agregar una habilidad nueva: crea un módulo en esta carpeta con
funciones bien documentadas y súmalas a TODAS aquí abajo.
"""

from . import (bluetooth, clima, correo, energia, internet, memoria, musica,
               noticias, paquetes, pantalla, portapapeles, recordatorios, sistema, techo,
               terminal, ventanas)

TODAS = [*sistema.HERRAMIENTAS, *bluetooth.HERRAMIENTAS, *clima.HERRAMIENTAS,
         *recordatorios.HERRAMIENTAS, *memoria.HERRAMIENTAS, *internet.HERRAMIENTAS,
         *correo.HERRAMIENTAS, *musica.HERRAMIENTAS, *ventanas.HERRAMIENTAS,
         *energia.HERRAMIENTAS, *portapapeles.HERRAMIENTAS,
         *noticias.HERRAMIENTAS, *pantalla.HERRAMIENTAS, *paquetes.HERRAMIENTAS,
         *techo.HERRAMIENTAS, *terminal.HERRAMIENTAS]

# Órdenes exactas que se cumplen al instante sin preguntarle a la IA (sin cuota ni
# internet). Cada atajo recibe el mensaje y devuelve la respuesta, o None si no es suyo.
ATAJOS = [*techo.ATAJOS]
