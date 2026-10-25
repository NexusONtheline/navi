"""Registro de herramientas de NAVI.

Para agregar una habilidad nueva: crea un módulo en esta carpeta con
funciones bien documentadas y súmalas a TODAS aquí abajo.
"""

from . import (bluetooth, clima, correo, energia, internet, memoria, musica,
               noticias, pantalla, portapapeles, recordatorios, sistema, ventanas)

TODAS = [*sistema.HERRAMIENTAS, *bluetooth.HERRAMIENTAS, *clima.HERRAMIENTAS,
         *recordatorios.HERRAMIENTAS, *memoria.HERRAMIENTAS, *internet.HERRAMIENTAS,
         *correo.HERRAMIENTAS, *musica.HERRAMIENTAS, *ventanas.HERRAMIENTAS,
         *energia.HERRAMIENTAS, *portapapeles.HERRAMIENTAS,
         *noticias.HERRAMIENTAS, *pantalla.HERRAMIENTAS]
