"""NAVI como mascota de escritorio: un PC beige de los 90 en la esquina, con globo de diálogo.

`navi --mascota` la deja siempre visible. Clic en la pantalla para escribirle (Enter
vacío o el botón del micrófono para hablarle), clic derecho para el menú. También
despierta con «NAVI, actívate» y con Super+N (`navi --abrir`). Reacciona si le tocas
un ojo, el teclado o la torre, y sus ojos siguen al ratón.

Privacidad: Wayland no deja ver el ratón fuera de nuestra ventana, así que fuera de
ella mira hacia la ventana que estés usando (solo su posición, nunca su contenido).
Nada de esto se guarda ni sale del PC.

En Sway (Wayland) usa gtk-layer-shell para quedarse pegada a la esquina por encima
de las ventanas; en escritorios X11 (Cinnamon, XFCE...) es una ventana sin bordes
siempre encima. GTK hace todo en un solo hilo: lo lento (Gemini, Whisper) va en
un hilo aparte que le pasa los cambios con GLib.idle_add.
"""

import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402
except (ValueError, ImportError):
    GtkLayerShell = None

from . import config, confirmaciones, senales  # noqa: E402
from .__main__ import SALIDAS  # noqa: E402
from .cerebro import Cerebro  # noqa: E402
from .oido import Oido  # noqa: E402
from .voz import Voz  # noqa: E402

ANCHO, ALTO = 228, 206  # lienzo del personaje
MARGEN = 18  # separación con el borde de la pantalla
MINUTOS_PARA_SOLTAR_OIDO = 10

# Paleta de Copland OS (la misma que la terminal)
AZUL = (0.62, 0.80, 1.0)
ROSA = (0.88, 0.27, 0.48)

ESTILO = b"""
.globo {
    background-color: rgba(12, 12, 18, 0.96);
    border: 1px solid #e0457b;
    border-radius: 12px;
    padding: 10px 12px;
}
.globo label { color: #d0d0d0; font-family: monospace; font-size: 10.5pt; }
.globo .titulo { color: #9ecbff; font-weight: bold; font-size: 9pt; }
.globo .usuario { color: #8a8a8a; font-style: italic; }
.globo .error { color: #e0457b; }
.globo entry {
    background: #050508; color: #d0d0d0; caret-color: #e0457b;
    border: 1px solid #3a3a48; border-radius: 6px; font-family: monospace;
}
.globo button {
    background: #1a1a24; color: #d0d0d0; border: 1px solid #3a3a48;
    border-radius: 6px; padding: 2px 10px; font-family: monospace; box-shadow: none;
}
.globo button:hover { border-color: #e0457b; color: #ffffff; }
"""


def _en_capa() -> bool:
    return GtkLayerShell is not None and GtkLayerShell.is_supported()


def _ventana_flotante(nombre: str, margen_abajo: int) -> Gtk.Window:
    """Ventana transparente, sin bordes, pegada a la esquina inferior derecha."""
    ventana = Gtk.Window(title=nombre)
    ventana.set_decorated(False)
    ventana.set_app_paintable(True)
    visual = ventana.get_screen().get_rgba_visual()
    if visual is not None:
        ventana.set_visual(visual)
    ventana.connect("draw", _fondo_transparente)
    if _en_capa():
        GtkLayerShell.init_for_window(ventana)
        GtkLayerShell.set_namespace(ventana, f"navi-{nombre}")
        GtkLayerShell.set_layer(ventana, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(ventana, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(ventana, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(ventana, GtkLayerShell.Edge.BOTTOM, margen_abajo)
        GtkLayerShell.set_margin(ventana, GtkLayerShell.Edge.RIGHT, MARGEN)
    else:
        ventana.set_keep_above(True)
        ventana.set_skip_taskbar_hint(True)
        ventana.set_skip_pager_hint(True)
        ventana.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        ventana.stick()
        ventana.connect("size-allocate", lambda w, _a: _a_la_esquina(w, margen_abajo))
    return ventana


def _fondo_transparente(_ventana, cr) -> bool:
    cr.save()  # el mismo lienzo se usa luego para dibujar el contenido
    cr.set_operator(0)  # CLEAR
    cr.paint()
    cr.restore()
    return False


def _a_la_esquina(ventana: Gtk.Window, margen_abajo: int) -> None:
    """X11: no hay anclas, así que la movemos a mano a la esquina del monitor."""
    pantalla = Gdk.Display.get_default()
    monitor = pantalla.get_primary_monitor() or pantalla.get_monitor(0)
    area = monitor.get_workarea()
    ancho, alto = ventana.get_size()
    ventana.move(area.x + area.width - ancho - MARGEN,
                 area.y + area.height - alto - margen_abajo)


def _texto_plano(texto: str) -> str:
    """Quita el formato markdown que a veces manda Gemini (**negritas**, # títulos)."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"^#+\s*", "", texto, flags=re.MULTILINE)
    return re.sub(r"^\s*[*-]\s+", "• ", texto, flags=re.MULTILINE)


# ---------------------------------------------------------------- el personaje

# Colores del PC beige de los 90, algo apagados (luz de cuarto de Lain)
BEIGE = (0.80, 0.76, 0.66)
BEIGE_SOMBRA = (0.58, 0.54, 0.46)
BEIGE_LUZ = (0.88, 0.85, 0.77)
CABLE = (0.34, 0.34, 0.41)

# Zonas del dibujo (sin contar el vaivén), para saber dónde hiciste clic
MONITOR = (20, 34, 124, 100)      # x, y, ancho, alto
PANTALLA = (32, 45, 100, 72)
TORRE = (158, 64, 56, 112)
TECLADO = (14, 160, 136, 24)
RATON = (168, 184, 20, 16)
OJOS_Y = 76
OJOS_X = (68, 96)  # centro de cada ojo

FRASES_OJO = [
    "¡Oye! Ese es mi ojo.",
    "Auch. En el Nexo también se siente.",
    "No me pinches, que te veo igual.",
    "Mis ojos son solo píxeles... pero son míos.",
]
FRASES_MAREO = ["Todo da vueltas en el Nexo...", "Demasiados clics. Me mareé."]

# Cursor retro (1 = borde, 2 = relleno), como el de los 90
_CURSOR = [
    "1           ", "11          ", "121         ", "1221        ", "12221       ",
    "122221      ", "1222221     ", "12222221    ", "122222221   ", "1222222221  ",
    "12222211111 ", "1221221     ", "121 1221    ", "11  1221    ", "1    1221   ",
    "     1221   ", "      11    ",
]


def cursor_retro(ventana: Gtk.Window):
    """El cursor de flecha pixelado de Copland OS, para cuando pasas sobre NAVI."""
    try:
        import cairo
        gi.require_foreign("cairo")
    except Exception:  # sin pycairo (python3-gi-cairo): cursor normal
        return None
    escala = 2
    superficie = cairo.ImageSurface(cairo.FORMAT_ARGB32, 12 * escala, 17 * escala)
    cr = cairo.Context(superficie)
    for fila, linea in enumerate(_CURSOR):
        for columna, pixel in enumerate(linea):
            if pixel == " ":
                continue
            cr.set_source_rgb(*((0.05, 0.05, 0.08) if pixel == "1" else (1.0, 0.92, 0.95)))
            cr.rectangle(columna * escala, fila * escala, escala, escala)
            cr.fill()
    try:
        return Gdk.Cursor.new_from_surface(ventana.get_display(), superficie, 0, 0)
    except TypeError:
        return None


def _solo_lo_solido(ventana: Gtk.Window) -> None:
    """Que los clics en lo transparente (cables, huecos) lleguen a la ventana de detrás."""
    try:
        import cairo
        gi.require_foreign("cairo")
    except Exception:
        return
    x, y, ancho, alto = MONITOR
    zonas = [(x, y, ancho, alto + 12), TORRE, TECLADO, RATON]  # +12: la peana
    ventana.input_shape_combine_region(cairo.Region(
        [cairo.RectangleInt(*(int(v) for v in zona)) for zona in zonas]))


def _dentro(zona, x: float, y: float) -> bool:
    zx, zy, ancho, alto = zona
    return zx <= x <= zx + ancho and zy <= y <= zy + alto


class Personaje(Gtk.DrawingArea):
    """Un PC beige de los 90 con cara en la pantalla, enredado en los cables del Nexo."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(ANCHO, ALTO)
        self.estado = "reposo"  # reposo · escuchando · pensando · hablando
        self._inicio = time.monotonic()
        self._parpadeo = 0.0  # momento en que empezó el último parpadeo
        self._proximo_parpadeo = time.monotonic() + 3
        self._mirada = [0.0, 0.0]        # hacia dónde miran los ojos ahora (suavizado)
        self.objetivo = (0.0, 0.0)       # hacia dónde quieren mirar (-1..1)
        self.encima = False              # el ratón está sobre NAVI
        self.ultima_actividad = time.monotonic()
        self._reaccion: tuple[str, float, int] | None = None  # (tipo, inicio, ojo)
        self._clics: list[tuple[float, float, float]] = []   # ondas de clic (x, y, inicio)
        self._ultimo_dibujo = 0.0
        self.connect("draw", self._dibujar)
        GLib.timeout_add(33, self._animar)

    # --- lo que pasa

    @property
    def dormida(self) -> bool:
        """Tras 3 minutos sin que nadie la toque, se duerme (salvapantallas)."""
        return (self.estado == "reposo" and not self.encima and self._reaccion is None
                and time.monotonic() - self.ultima_actividad > 180)

    def despertar(self) -> None:
        self.ultima_actividad = time.monotonic()

    def reaccionar(self, tipo: str, ojo: int = 0) -> None:
        self._reaccion = (tipo, time.monotonic(), ojo)
        self.despertar()

    def onda(self, x: float, y: float) -> None:
        self._clics.append((x, y, time.monotonic()))

    def zona(self, x: float, y: float) -> str:
        """Qué parte de NAVI está en (x, y): ojo0, ojo1, pantalla, teclado, torre, raton."""
        for i, ojo_x in enumerate(OJOS_X):
            if abs(x - ojo_x) < 11 and abs(y - OJOS_Y) < 11:
                return f"ojo{i}"
        for nombre, zona in (("pantalla", MONITOR), ("teclado", TECLADO),
                             ("torre", TORRE), ("raton", RATON)):
            if _dentro(zona, x, y):
                return nombre
        return ""

    # --- animación

    def _animar(self) -> bool:
        ahora = time.monotonic()
        if ahora >= self._proximo_parpadeo:
            self._parpadeo = ahora
            self._proximo_parpadeo = ahora + random.uniform(2.5, 6)
        if self._reaccion and ahora - self._reaccion[1] > 2.5:
            self._reaccion = None
        self._clics = [c for c in self._clics if ahora - c[2] < 0.6]

        # Los ojos se acercan poco a poco a su objetivo
        for i in range(2):
            self._mirada[i] += (self.objetivo[i] - self._mirada[i]) * 0.25

        # Fluido (30 imágenes/s) cuando hay algo que ver; en reposo, 4 (menos CPU)
        movida = self.encima or self._reaccion or self._clics or self.estado != "reposo" \
            or ahora - self._parpadeo < 0.2 \
            or abs(self.objetivo[0] - self._mirada[0]) + abs(self.objetivo[1] - self._mirada[1]) > 0.02
        if not movida and ahora - self._ultimo_dibujo < 0.25:
            return True
        self._ultimo_dibujo = ahora
        self.queue_draw()
        return True

    def _dibujar(self, _widget, cr) -> bool:
        t = time.monotonic() - self._inicio
        cr.set_operator(0)  # CLEAR: fondo transparente
        cr.paint()
        cr.set_operator(2)  # OVER

        self._cables_de_arriba(cr, t)
        # Sombra en la mesa
        cr.save()
        cr.translate(ANCHO / 2, ALTO - 9)
        cr.scale(1, 0.12)
        cr.arc(0, 0, ANCHO / 2 - 6, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.fill()
        cr.restore()

        self._torre(cr, t)
        self._cable(cr, (TORRE[0] + 6, TORRE[1] + 30), (MONITOR[0] + MONITOR[2] - 4, 92),
                    t, 8)  # monitor ↔ torre
        self._monitor(cr, t)
        self._teclado(cr, t)
        self._raton(cr, t)
        self._ondas_de_clic(cr)
        return False

    def _cable(self, cr, desde, hasta, t: float, caida: float, grosor: float = 2.2,
               fase: float = 0.0) -> None:
        (x1, y1), (x2, y2) = desde, hasta
        vaiven = math.sin(t * 1.2 + fase) * 3
        cr.move_to(x1, y1)
        cr.curve_to(x1 + (x2 - x1) * 0.3 + vaiven, y1 + caida, x1 + (x2 - x1) * 0.7 - vaiven,
                    y2 + caida, x2, y2)
        cr.set_source_rgb(*CABLE)
        cr.set_line_width(grosor)
        cr.stroke()

    def _cables_de_arriba(self, cr, t: float) -> None:
        """Los cables del Nexo: bajan del techo y se enredan detrás del PC."""
        for i, (x, grosor, fase) in enumerate(((44, 2.4, 0), (88, 1.6, 1.3), (118, 3.0, 2.1),
                                                (176, 2.0, 0.7), (204, 1.4, 2.8))):
            vaiven = math.sin(t * 0.9 + fase) * 5
            fin_x = 70 + i * 30
            cr.move_to(x, 0)
            cr.curve_to(x + vaiven, 30, fin_x - vaiven, 20, fin_x, MONITOR[1] + 20)
            cr.set_source_rgba(*CABLE, 0.95)
            cr.set_line_width(grosor)
            cr.stroke()
        # Y uno que sale de la torre hacia fuera de la pantalla
        self._cable(cr, (TORRE[0] + TORRE[2] - 8, TORRE[1] + TORRE[2] + 40), (ANCHO, ALTO - 30),
                    t, 14, 2.6, 1.0)

    def _monitor(self, cr, t: float) -> None:
        x, y, ancho, alto = MONITOR
        # Peana
        cr.move_to(x + 40, y + alto)
        cr.line_to(x + ancho - 40, y + alto)
        cr.line_to(x + ancho - 30, y + alto + 12)
        cr.line_to(x + 30, y + alto + 12)
        cr.close_path()
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.fill()
        # Carcasa con bisel
        _rectangulo(cr, x, y, ancho, alto, 9)
        cr.set_source_rgb(*BEIGE)
        cr.fill_preserve()
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.set_line_width(1.5)
        cr.stroke()
        cr.move_to(x + 4, y + 3)
        cr.line_to(x + ancho - 8, y + 3)
        cr.set_source_rgb(*BEIGE_LUZ)
        cr.set_line_width(1.2)
        cr.stroke()
        # Rejilla y lucecita bajo la pantalla
        for i in range(5):
            cr.rectangle(x + 10 + i * 5, y + alto - 9, 3, 4)
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.fill()
        encendida = self.estado != "reposo" and int(t * 4) % 2
        cr.arc(x + ancho - 12, y + alto - 7, 2, 0, 2 * math.pi)
        cr.set_source_rgb(*(ROSA if encendida else (0.25, 0.65, 0.35)))
        cr.fill()

        # Pantalla (un CRT curvo, oscuro, con el brillo de Copland OS)
        px, py, pancho, palto = PANTALLA
        _rectangulo(cr, px, py, pancho, palto, 8)
        cr.set_source_rgb(0.02, 0.03, 0.05)
        cr.fill()
        color = ROSA if self.estado == "escuchando" else AZUL
        dormida = self.dormida
        brillo = 0.05 if dormida else 0.10 + 0.03 * math.sin(t * 3)
        _rectangulo(cr, px, py, pancho, palto, 8)
        cr.set_source_rgba(*color, brillo)
        cr.fill()
        cr.set_source_rgba(*color, 0.05)
        for linea in range(int(py), int(py + palto), 3):  # líneas de barrido
            cr.rectangle(px, linea, pancho, 1)
        cr.fill()
        if self.estado == "pensando":  # una franja que recorre la pantalla
            franja = py + (t * 50) % palto
            cr.set_source_rgba(*color, 0.18)
            cr.rectangle(px, franja, pancho, 4)
            cr.fill()

        cr.save()
        _rectangulo(cr, px, py, pancho, palto, 8)
        cr.clip()
        if dormida:
            self._dormir(cr, t, color)
        else:
            self._cara(cr, t, color)
        if self._reaccion and self._reaccion[0] == "teclas":
            self._tecleo(cr, color)
        cr.restore()

        # Reflejo del cristal
        cr.move_to(px + 8, py + 6)
        cr.curve_to(px + 30, py + 2, px + 60, py + 2, px + pancho - 12, py + 6)
        cr.set_source_rgba(1, 1, 1, 0.07)
        cr.set_line_width(3)
        cr.stroke()

        if self.estado == "escuchando":
            self._ondas(cr, t, x - 4, y + alto / 2)

    def _cara(self, cr, t: float, color) -> None:
        reaccion = self._reaccion[0] if self._reaccion else ""
        mx, my = self._mirada[0] * 7, self._mirada[1] * 5
        if self.estado == "pensando":
            mx, my = 5 * math.sin(t * 2), -4
        avance = time.monotonic() - self._parpadeo
        abierto = 1.0 if avance > 0.15 else abs(avance / 0.075 - 1)
        alto_ojo = 15 if self.estado == "escuchando" or self.encima else 12

        cr.set_source_rgba(*color, 0.95)
        for i, ojo_x in enumerate(OJOS_X):
            cx, cy = ojo_x + mx, OJOS_Y + my
            if reaccion == "mareo":  # ojos en espiral
                cr.save()
                cr.translate(cx, cy)
                cr.rotate(t * 8 * (1 if i else -1))
                for paso in range(28):
                    angulo, radio = paso * 0.5, paso * 0.25
                    cr.line_to(math.cos(angulo) * radio, math.sin(angulo) * radio)
                cr.restore()
                cr.set_line_width(1.6)
                cr.stroke()
                continue
            if reaccion == "ojo" and self._reaccion[2] == i:  # el ojo que pinchaste: > <
                lado = 1 if i == 0 else -1
                cr.move_to(cx - 5 * lado, cy - 5)
                cr.line_to(cx + 5 * lado, cy)
                cr.line_to(cx - 5 * lado, cy + 5)
                cr.set_line_width(2.2)
                cr.stroke()
                continue
            cr.save()
            cr.translate(cx, cy)
            cr.scale(1, max(0.12, abierto * (0.5 if reaccion == "ojo" else 1)))
            _rectangulo(cr, -5, -alto_ojo / 2, 10, alto_ojo, 3)
            cr.restore()
            cr.fill()

        # Boca
        bx, by = (OJOS_X[0] + OJOS_X[1]) / 2 + mx * 0.5, OJOS_Y + 20 + my * 0.5
        if self.estado == "hablando":
            boca = abs(math.sin(t * 11)) * 5 + abs(math.sin(t * 7)) * 2
            cr.save()
            cr.translate(bx, by)
            cr.scale(1, max(0.15, boca / 7))
            cr.arc(0, 0, 7, 0, 2 * math.pi)
            cr.restore()
            cr.fill()
        elif reaccion in ("ojo", "mareo"):  # boquita ondulada
            cr.move_to(bx - 8, by)
            for paso in range(1, 9):
                cr.line_to(bx - 8 + paso * 2, by + (2 if paso % 2 else -2))
            cr.set_line_width(1.6)
            cr.stroke()
        else:
            sonrisa = 4 if self.encima else 0  # sonríe cuando le pasas el ratón
            cr.move_to(bx - 7, by)
            cr.curve_to(bx - 3, by + sonrisa, bx + 3, by + sonrisa, bx + 7, by)
            cr.set_line_width(1.8)
            cr.stroke()

    def _dormir(self, cr, t: float, color) -> None:
        """Salvapantallas: ojos cerrados y unas zetas que suben."""
        cr.set_source_rgba(*color, 0.6)
        cr.set_line_width(2)
        for ojo_x in OJOS_X:
            cr.move_to(ojo_x - 6, OJOS_Y + 2)
            cr.curve_to(ojo_x - 2, OJOS_Y + 6, ojo_x + 2, OJOS_Y + 6, ojo_x + 6, OJOS_Y + 2)
            cr.stroke()
        cr.select_font_face("monospace")
        for i in range(3):
            fase = (t * 0.4 + i / 3) % 1
            cr.set_font_size(7 + fase * 6)
            cr.set_source_rgba(*color, 1 - fase)
            cr.move_to(108 + fase * 12, 70 - fase * 22)
            cr.show_text("z")

    def _tecleo(self, cr, color) -> None:
        """Al pulsar el teclado, aparece texto en la pantalla como en Copland OS."""
        inicio = self._reaccion[1]
        texto = "> conectando_"[:int((time.monotonic() - inicio) * 14)]
        cr.select_font_face("monospace")
        cr.set_font_size(8)
        cr.set_source_rgba(*color, 0.9)
        cr.move_to(PANTALLA[0] + 6, PANTALLA[1] + PANTALLA[3] - 6)
        cr.show_text(texto)

    def _torre(self, cr, t: float) -> None:
        x, y, ancho, alto = TORRE
        _rectangulo(cr, x, y, ancho, alto, 4)
        cr.set_source_rgb(*BEIGE)
        cr.fill_preserve()
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.set_line_width(1.5)
        cr.stroke()
        # Bahías y disquetera
        for i in range(2):
            cr.rectangle(x + 7, y + 10 + i * 13, ancho - 14, 9)
            cr.set_source_rgb(*BEIGE_LUZ)
            cr.fill_preserve()
            cr.set_source_rgb(*BEIGE_SOMBRA)
            cr.set_line_width(1)
            cr.stroke()
        disquete = self._reaccion and self._reaccion[0] == "disquete"
        sale = min(1, (time.monotonic() - self._reaccion[1]) * 3) * 6 if disquete else 0
        cr.rectangle(x + 12, y + 44, ancho - 24, 3)
        cr.set_source_rgb(0.2, 0.2, 0.22)
        cr.fill()
        if sale:  # el disquete asoma
            cr.rectangle(x + 13, y + 44 + 1, ancho - 26, sale)
            cr.set_source_rgb(0.15, 0.17, 0.35)
            cr.fill()
        # Lucecitas: encendido y disco duro (parpadea cuando piensa o la tocas)
        cr.arc(x + ancho - 12, y + 62, 2, 0, 2 * math.pi)
        cr.set_source_rgb(0.25, 0.65, 0.35)
        cr.fill()
        trabajando = self.estado == "pensando" or disquete
        cr.arc(x + ancho - 12, y + 70, 2, 0, 2 * math.pi)
        cr.set_source_rgb(*((1.0, 0.6, 0.1) if trabajando and random.random() < 0.6
                            else (0.35, 0.25, 0.1)))
        cr.fill()
        # Botón y rejilla
        cr.arc(x + 14, y + 66, 4, 0, 2 * math.pi)
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.fill()
        for i in range(6):
            cr.rectangle(x + 10, y + 84 + i * 4, ancho - 20, 1.5)
        cr.fill()

    def _teclado(self, cr, t: float) -> None:
        x, y, ancho, alto = TECLADO
        cr.move_to(x + 6, y)
        cr.line_to(x + ancho - 6, y)
        cr.line_to(x + ancho, y + alto)
        cr.line_to(x, y + alto)
        cr.close_path()
        cr.set_source_rgb(*BEIGE)
        cr.fill_preserve()
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.set_line_width(1.2)
        cr.stroke()
        pulsando = self._reaccion and self._reaccion[0] == "teclas"
        aleatorio = random.Random(int(t * 12))  # cambia las teclas pulsadas 12 veces/s
        for fila in range(3):
            for col in range(14):
                tx = x + 9 + col * 8.6 + fila * 1.5
                ty = y + 4 + fila * 6.5
                pulsada = pulsando and aleatorio.random() < 0.12
                cr.rectangle(tx, ty + (1 if pulsada else 0), 6.6, 4.6)
                cr.set_source_rgb(*(ROSA if pulsada else BEIGE_LUZ))
                cr.fill()

    def _raton(self, cr, t: float) -> None:
        x, y, ancho, alto = RATON
        self._cable(cr, (x + ancho / 2, y), (TORRE[0] + 20, TORRE[1] + TORRE[3] - 2), t, -6,
                    1.4, 2.0)
        _rectangulo(cr, x, y, ancho, alto, 6)
        cr.set_source_rgb(*BEIGE)
        cr.fill_preserve()
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.set_line_width(1.2)
        cr.stroke()
        # El botón se hunde cuando haces clic en cualquier parte de NAVI
        clic = any(time.monotonic() - c[2] < 0.15 for c in self._clics)
        cr.rectangle(x + 2, y + 2, ancho / 2 - 3, 6)
        cr.set_source_rgb(*(ROSA if clic else BEIGE_LUZ))
        cr.fill()
        cr.move_to(x + ancho / 2, y + 1)
        cr.line_to(x + ancho / 2, y + 8)
        cr.set_source_rgb(*BEIGE_SOMBRA)
        cr.set_line_width(1)
        cr.stroke()

    def _ondas_de_clic(self, cr) -> None:
        """Al hacer clic: cuadritos pixelados que se expanden, estilo Copland OS."""
        ahora = time.monotonic()
        for x, y, inicio in self._clics:
            avance = (ahora - inicio) / 0.6
            lado = 4 + avance * 26
            cr.set_source_rgba(*ROSA, 1 - avance)
            for paso in range(0, int(lado * 4), 4):  # borde punteado: píxeles sueltos
                posicion = paso / 4
                for px, py in ((x - lado / 2 + posicion, y - lado / 2),
                               (x - lado / 2 + posicion, y + lado / 2),
                               (x - lado / 2, y - lado / 2 + posicion),
                               (x + lado / 2, y - lado / 2 + posicion)):
                    if paso % 8 == 0:
                        cr.rectangle(px, py, 2, 2)
            cr.fill()

    def _ondas(self, cr, t: float, x: float, y: float) -> None:
        """Ondas que salen del monitor mientras te escucha."""
        cr.set_line_width(1.6)
        for i in range(3):
            fase = (t * 1.5 + i / 3) % 1
            cr.arc(x + 6, y, 6 + fase * 12, math.pi - 0.6, math.pi + 0.6)
            cr.set_source_rgba(*ROSA, 1 - fase)
            cr.stroke()


def _rectangulo(cr, x: float, y: float, ancho: float, alto: float, radio: float) -> None:
    cr.new_sub_path()
    cr.arc(x + ancho - radio, y + radio, radio, -math.pi / 2, 0)
    cr.arc(x + ancho - radio, y + alto - radio, radio, 0, math.pi / 2)
    cr.arc(x + radio, y + alto - radio, radio, math.pi / 2, math.pi)
    cr.arc(x + radio, y + radio, radio, math.pi, 3 * math.pi / 2)
    cr.close_path()


# ---------------------------------------------------------------- el globo

class Globo:
    """El globo de diálogo: muestra lo que dice NAVI, te deja escribir y pregunta sí/no."""

    def __init__(self, al_enviar, al_escuchar, al_responder) -> None:
        self._al_responder = al_responder  # p. ej. dejar de escuchar si respondió con un botón
        self.ventana = _ventana_flotante("globo", MARGEN + ALTO - 6)
        self._ocultar_id = 0

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        caja.get_style_context().add_class("globo")
        caja.set_size_request(280, -1)
        caja.set_margin_bottom(2)

        self._titulo = Gtk.Label(label="NAVI", xalign=0)
        self._titulo.get_style_context().add_class("titulo")
        self._texto = Gtk.Label(xalign=0, wrap=True, selectable=False)
        self._texto.set_max_width_chars(42)
        self._texto.set_line_wrap_mode(2)  # palabra, y si no cabe, carácter
        self._desplazable = Gtk.ScrolledWindow()
        self._desplazable.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._desplazable.set_propagate_natural_height(True)
        self._desplazable.set_max_content_height(320)
        self._desplazable.add(self._texto)

        # Fila para escribir
        self._fila_escribir = Gtk.Box(spacing=6)
        self.entrada = Gtk.Entry(placeholder_text="escríbeme…")
        self.entrada.set_hexpand(True)
        self.entrada.connect("activate", lambda e: al_enviar(e.get_text().strip()))
        self.entrada.connect("key-press-event", self._tecla)
        microfono = Gtk.Button(label="🎙")
        microfono.set_tooltip_text("Hablarle (o Enter sin escribir nada)")
        microfono.connect("clicked", lambda _b: al_escuchar())
        self._fila_escribir.pack_start(self.entrada, True, True, 0)
        self._fila_escribir.pack_start(microfono, False, False, 0)

        # Fila para responder sí / no
        self._fila_si_no = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        self._respuesta: queue.Queue[str] | None = None
        for texto in ("No", "Sí"):
            boton = Gtk.Button(label=texto)
            boton.connect("clicked", lambda _b, t=texto: self.responder(t.lower()))
            self._fila_si_no.pack_start(boton, False, False, 0)

        caja.pack_start(self._titulo, False, False, 0)
        caja.pack_start(self._desplazable, False, False, 0)
        caja.pack_start(self._fila_escribir, False, False, 0)
        caja.pack_start(self._fila_si_no, False, False, 0)

        # Clic en el texto: cerrar el globo
        evento = Gtk.EventBox()
        evento.add(caja)
        evento.connect("button-press-event", self._clic)
        self.ventana.add(evento)
        evento.show_all()
        self._fila_si_no.hide()

    # --- mostrar cosas

    def mostrar(self, texto: str, estilo: str = "", escribir: bool = False,
                titulo: str = "NAVI") -> None:
        self._cancelar_ocultar()
        self._titulo.set_text(titulo)
        contexto = self._texto.get_style_context()
        for clase in ("usuario", "error"):
            contexto.remove_class(clase)
        if estilo:
            contexto.add_class(estilo)
        self._texto.set_text(_texto_plano(texto))
        self._texto.set_visible(bool(texto))
        self._desplazable.set_visible(bool(texto))
        self._fila_escribir.set_visible(escribir)
        self._fila_si_no.set_visible(self._respuesta is not None)
        self.ventana.resize(1, 1)  # que se encoja al contenido
        self.ventana.show()
        self._teclado(escribir)
        if escribir:
            self.entrada.set_text("")
            self.entrada.grab_focus()
            self.ventana.present()

    def escribir(self) -> None:
        self.mostrar("", escribir=True)

    def ocultar(self) -> None:
        self._cancelar_ocultar()
        self._teclado(False)
        self.ventana.hide()

    def ocultar_en(self, segundos: float) -> None:
        self._cancelar_ocultar()
        self._ocultar_id = GLib.timeout_add(int(segundos * 1000), self._ocultar_ahora)

    @property
    def escribiendo(self) -> bool:
        return self.ventana.get_visible() and self._fila_escribir.get_visible()

    # --- preguntas sí / no (las hace confirmaciones.py desde el hilo del cerebro)

    def preguntar(self, pregunta: str, respuesta: "queue.Queue[str]") -> None:
        self._respuesta = respuesta
        self.mostrar(pregunta, escribir=True)
        self.entrada.set_placeholder_text("sí o no")

    def responder(self, texto: str) -> bool:
        """Entrega la respuesta a la pregunta pendiente. False si no había ninguna."""
        if self._respuesta is None:
            return False
        self._respuesta.put(texto)
        self._respuesta = None
        self._al_responder()
        self.entrada.set_placeholder_text("escríbeme…")
        self._fila_si_no.hide()
        return True

    # --- detalles

    def _teclado(self, activo: bool) -> None:
        if _en_capa():
            # ON_DEMAND: recibe el teclado, pero lo suelta si haces clic en otra ventana
            modo = (GtkLayerShell.KeyboardMode.ON_DEMAND if activo
                    else GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_keyboard_mode(self.ventana, modo)
        else:
            self.ventana.set_accept_focus(activo)

    def _tecla(self, _entrada, evento) -> bool:
        if evento.keyval == Gdk.KEY_Escape:
            if not self.responder("no"):
                self.ocultar()
            return True
        return False

    def _clic(self, _widget, evento) -> bool:
        if evento.button == 1 and not self.escribiendo and self._respuesta is None:
            self.ocultar()
        return False

    def _ocultar_ahora(self) -> bool:
        self._ocultar_id = 0
        if not self.escribiendo and self._respuesta is None:
            self.ocultar()
        return False

    def _cancelar_ocultar(self) -> None:
        if self._ocultar_id:
            GLib.source_remove(self._ocultar_id)
            self._ocultar_id = 0


# ---------------------------------------------------------------- la mascota

class Mascota:
    def __init__(self, buenos_dias: bool) -> None:
        proveedor = Gtk.CssProvider()
        proveedor.load_from_data(ESTILO)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.personaje = Personaje()
        self.ventana = _ventana_flotante("mascota", MARGEN)
        evento = Gtk.EventBox()
        evento.add(self.personaje)
        evento.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                          | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        evento.connect("button-press-event", self._clic)
        evento.connect("motion-notify-event", self._movimiento)
        evento.connect("enter-notify-event", self._entra)
        evento.connect("leave-notify-event", self._sale)
        self.ventana.add(evento)
        self.ventana.show_all()
        self._cursor = cursor_retro(self.ventana)
        _solo_lo_solido(self.ventana)
        self._clics_en_ojos: list[float] = []
        self._vigilar_foco()

        self.pedidos: queue.Queue[tuple[str, str]] = queue.Queue()
        self.voz = Voz()
        self.oido = Oido(perezoso=True)
        self.globo = Globo(self._enviar, lambda: self.pedidos.put(("escuchar", "")),
                           self.oido.parar.set)
        self.por_voz = False  # si el último mensaje fue hablado, las preguntas también
        self.ocupada = False

        confirmaciones.registrar(self._preguntar)
        self.tuberia = senales.abrir_tuberia()
        if self.tuberia is not None:
            GLib.io_add_watch(self.tuberia, GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._tuberia)
        GLib.timeout_add(150, self._vigilar_voz)
        GLib.timeout_add_seconds(60, self._soltar_oido)

        threading.Thread(target=self._cerebro, args=(buenos_dias,), daemon=True).start()

    # --- lo que hace el usuario

    def _clic(self, _widget, evento) -> bool:
        self.personaje.onda(evento.x, evento.y)
        if evento.button == 3:
            self._menu(evento)
            return True
        if evento.button != 1:
            return True
        zona = self.personaje.zona(evento.x, evento.y)
        if self.personaje.estado == "escuchando":
            self.oido.parar.set()
        elif zona.startswith("ojo"):
            self._pincharon_ojo(int(zona[-1]))
        elif zona == "teclado":  # teclado = escribirle
            self.personaje.reaccionar("teclas")
            self.globo.escribir()
        elif zona == "torre":  # torre = cómo está el PC por dentro
            self.personaje.reaccionar("disquete")
            threading.Thread(target=self._estado_del_pc, daemon=True).start()
        elif zona == "raton":
            self.personaje.despertar()
        elif self.voz.hablando:
            self.voz.callar()
        elif self.globo.escribiendo:
            self.globo.ocultar()
        else:
            self.globo.escribir()
        return True

    def _pincharon_ojo(self, ojo: int) -> None:
        ahora = time.monotonic()
        self._clics_en_ojos = [t for t in self._clics_en_ojos if ahora - t < 2.5] + [ahora]
        if len(self._clics_en_ojos) >= 3:  # muchos clics seguidos: se marea
            self._clics_en_ojos.clear()
            self.personaje.reaccionar("mareo")
            self._comentar(random.choice(FRASES_MAREO))
        else:
            self.personaje.reaccionar("ojo", ojo)
            self._comentar(random.choice(FRASES_OJO))

    def _comentar(self, texto: str) -> None:
        """Una frase corta de NAVI que no pasa por Gemini (no gasta cuota)."""
        if self.ocupada or self.globo.escribiendo:
            return
        self.globo.mostrar(texto)
        self.voz.decir(texto)
        self.globo.ocultar_en(4)

    def _estado_del_pc(self) -> None:
        from .herramientas.sistema import estado_sistema
        texto = estado_sistema()  # todo local: CPU, RAM, temperatura, batería
        self._en_gtk(lambda: self.ocupada or (self.globo.mostrar(texto, titulo="NAVI · sistema"),
                                              self.globo.ocultar_en(8)))

    # --- los ojos siguen al ratón (dentro de la mascota) o a la ventana que uses

    def _mirar_a(self, x: float, y: float, alcance_x: float, alcance_y: float) -> None:
        """Apunta los ojos hacia (x, y), en coordenadas del lienzo del personaje."""
        centro_x, centro_y = sum(OJOS_X) / 2, OJOS_Y
        self.personaje.objetivo = (max(-1.0, min(1.0, (x - centro_x) / alcance_x)),
                                   max(-1.0, min(1.0, (y - centro_y) / alcance_y)))

    def _movimiento(self, _widget, evento) -> bool:
        self.personaje.despertar()
        self._mirar_a(evento.x, evento.y, 90, 70)
        return False

    def _entra(self, _widget, _evento) -> bool:
        self.personaje.encima = True
        self.personaje.despertar()
        if self._cursor and self.ventana.get_window():
            self.ventana.get_window().set_cursor(self._cursor)
        return False

    def _sale(self, _widget, _evento) -> bool:
        self.personaje.encima = False
        self.personaje.objetivo = (0.0, 0.0)
        return False

    def _origen_en_pantalla(self) -> tuple[float, float]:
        """Dónde está el lienzo del personaje en la pantalla (esquina inferior derecha)."""
        pantalla = Gdk.Display.get_default()
        ventana = self.ventana.get_window()
        monitor = (pantalla.get_monitor_at_window(ventana) if ventana else None) \
            or pantalla.get_primary_monitor() or pantalla.get_monitor(0)
        area = monitor.get_geometry()
        return area.x + area.width - MARGEN - ANCHO, area.y + area.height - MARGEN - ALTO

    def _vigilar_foco(self) -> None:
        if _en_capa() and shutil.which("swaymsg"):
            # Sway avisa cada vez que cambias de ventana; solo usamos su posición
            self._sway = subprocess.Popen(
                ["swaymsg", "-r", "-m", "-t", "subscribe", '["window"]'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self._pendiente = b""
            GLib.io_add_watch(self._sway.stdout.fileno(), GLib.PRIORITY_LOW,
                              GLib.IO_IN | GLib.IO_HUP, self._evento_de_sway)
        elif not _en_capa():
            # X11 sí deja saber dónde está el ratón en toda la pantalla
            GLib.timeout_add(100, self._raton_x11)

    def _evento_de_sway(self, fd, condicion) -> bool:
        if condicion & GLib.IO_HUP:
            return False
        self._pendiente += os.read(fd, 65536)
        *lineas, self._pendiente = self._pendiente.split(b"\n")
        for linea in lineas:
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if evento.get("change") != "focus" or self.personaje.encima:
                continue
            rect = evento.get("container", {}).get("rect") or {}
            if rect.get("width"):
                ox, oy = self._origen_en_pantalla()
                self._mirar_a(rect["x"] + rect["width"] / 2 - ox,
                              rect["y"] + rect["height"] / 2 - oy, 500, 350)
        return True

    def _raton_x11(self) -> bool:
        if not self.personaje.encima:
            puntero = Gdk.Display.get_default().get_default_seat().get_pointer()
            _pantalla, x, y = puntero.get_position()
            ox, oy = self._origen_en_pantalla()
            self._mirar_a(x - ox, y - oy, 500, 350)
        return True

    def _menu(self, evento) -> None:
        menu = Gtk.Menu()
        privado = senales.en_modo_privado()
        opciones = [
            ("Hablarle", lambda: self.pedidos.put(("escuchar", ""))),
            ("Escribirle", self.globo.escribir),
            ("Activar la voz" if not self.voz.activa_usuario else "Silenciar la voz",
             self._alternar_voz),
            ("Salir del modo privado" if privado else "Modo privado (no escucha «actívate»)",
             lambda: senales.modo_privado(not privado)),
            ("Cerrar NAVI", Gtk.main_quit),
        ]
        for texto, accion in opciones:
            item = Gtk.MenuItem(label=texto)
            item.connect("activate", lambda _i, a=accion: a())
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(evento)

    def _alternar_voz(self) -> None:
        self.voz.activa_usuario = not self.voz.activa_usuario
        if not self.voz.activa_usuario:
            self.voz.callar()

    def _enviar(self, texto: str) -> None:
        if self.globo.responder(texto):  # era la respuesta a una pregunta sí/no
            return
        if self.ocupada:
            return
        self.globo.ocultar()
        self.pedidos.put(("escuchar", "") if not texto else ("texto", texto))

    def _tuberia(self, fd, _condicion) -> bool:
        for mensaje in senales.leer_mensajes(fd):
            if mensaje == "escuchar" and not self.ocupada:
                self.pedidos.put(("escuchar", ""))
            elif mensaje == "escribir":
                self.globo.escribir()
        return True

    def _vigilar_voz(self) -> bool:
        """La boca se mueve mientras suena la voz; el globo se va cuando termina."""
        if self.personaje.estado in ("reposo", "hablando"):
            self.personaje.estado = "hablando" if self.voz.hablando else "reposo"
        return True

    def _soltar_oido(self) -> bool:
        """Tras un rato sin hablarle, Whisper se descarga para devolver ~500 MB de RAM."""
        if (self.oido.cargado and not self.ocupada
                and time.monotonic() - self.oido.ultimo_uso > MINUTOS_PARA_SOLTAR_OIDO * 60):
            self.oido.soltar()
        return True

    # --- puente entre el hilo del cerebro y GTK

    def _en_gtk(self, funcion, *args) -> None:
        GLib.idle_add(lambda: funcion(*args) and False)

    def _estado(self, estado: str) -> None:
        self._en_gtk(setattr, self.personaje, "estado", estado)
        self.personaje.despertar()

    def _decir(self, texto: str, estilo: str = "") -> None:
        self._en_gtk(self.globo.mostrar, texto, estilo)
        if estilo != "error":
            self.voz.decir(texto)
        # Lo dejamos el tiempo justo para leerlo (y que termine de hablar)
        self._en_gtk(self.globo.ocultar_en, max(7.0, len(texto) / 14))

    def _preguntar(self, pregunta: str) -> str:
        """confirmaciones.preguntar() llega aquí, desde el hilo del cerebro."""
        respuesta: queue.Queue[str] = queue.Queue()
        self._estado("reposo")
        self._en_gtk(self.globo.preguntar, pregunta, respuesta)
        if self.voz.activa:
            self.voz.decir(pregunta)
            self.voz.esperar()
        if self.por_voz and self.oido.disponible and respuesta.empty():
            dicho = self._escuchar(callado=True)
            if dicho:
                self._en_gtk(self.globo.responder, dicho)
        try:
            texto = respuesta.get(timeout=60)
        except queue.Empty:
            texto = "no"
            self._en_gtk(self.globo.responder, "no")
        self._estado("pensando")
        return texto

    # --- el hilo del cerebro

    def _escuchar(self, callado: bool = False) -> str:
        self.voz.callar()
        self._estado("escuchando")
        if not callado:
            self._en_gtk(self.globo.mostrar, "te escucho…", "usuario")
        try:
            with senales.ocupada():
                audio = self.oido.escuchar()
            self._estado("pensando")
            texto = self.oido.transcribir(audio)
        finally:
            self._estado("reposo")
        if not texto and not callado:
            self._decir(self.oido.problema or "No te escuché. Haz clic en mí e intenta de nuevo.",
                        "error")
        return texto

    def _cerebro(self, buenos_dias: bool) -> None:
        cerebro = Cerebro()
        if buenos_dias:
            from .saludo import _datos, pedido_de_saludo
            time.sleep(8)  # que terminen de conectarse el wifi y los audífonos
            self._estado("pensando")
            self._responder(cerebro, pedido_de_saludo(_datos()), mostrar_pedido=False)
            self.voz.esperar()
            if self.oido.disponible:
                self.pedidos.put(("escuchar", ""))

        while True:
            tipo, texto = self.pedidos.get()
            self.ocupada = True
            try:
                self.por_voz = tipo == "escuchar"
                if self.por_voz:
                    if not self.oido.disponible:
                        self._decir("No tengo oídos: revisa NAVI_OIDO en tu .env.", "error")
                        continue
                    texto = self._escuchar()
                    if not texto:
                        continue
                self._responder(cerebro, texto)
            except Exception as e:  # que un fallo raro nunca mate a la mascota
                print(f"mascota: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                self._decir(f"Algo falló: {type(e).__name__}", "error")
            finally:
                self.ocupada = False
                self._estado("reposo")

    def _responder(self, cerebro: Cerebro, texto: str, mostrar_pedido: bool = True) -> None:
        if texto.lower().strip(" .!¡") in SALIDAS:
            self._decir("Desconectando. Recuerda: todos estamos conectados.")
            return
        if texto.lower() in ("/voz", "silencio"):
            self._en_gtk(self._alternar_voz)
            return
        if mostrar_pedido:
            self._en_gtk(self.globo.mostrar, f"«{texto}»", "usuario")
        self._estado("pensando")
        respuesta, es_error = cerebro.responder_seguro(texto)
        self._estado("reposo")
        self._decir(respuesta, "error" if es_error else "")


def main(buenos_dias: bool = False) -> None:
    config.validar()
    if senales.pid_navi():
        # Ya hay una NAVI abierta: le pedimos que te deje escribir en vez de abrir otra
        senales.avisar_a_navi("escribir")
        return
    Mascota(buenos_dias)
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    finally:
        senales.cerrar_tuberia()
