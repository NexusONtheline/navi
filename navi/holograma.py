"""El holograma: NAVI de cuerpo entero proyectada en el techo.

El cuerpo sigue el arte conceptual RETRO-UNIT-01: androide beige con un monitor CRT
de cabeza (la cara pixelada de la mascota), la torre de mochila con los cables del
Nexo y un teclado en el antebrazo. Dos estilos: «color» (beige) y «lineas» (de luz).

Vive dentro de la mascota (`navi --mascota`) y hace lo mismo que ella: escucha,
piensa y habla, con la boca al ritmo de su voz. Se dibuja sobre negro porque en un
proyector el negro es ausencia de luz: solo se ve su figura, como si flotara.
Puede llevar a sus pies las barras de audio del modo techo (cava, sin ventana).

Las órdenes llegan por la tubería de senales («holograma:HDMI-A-1», «barras:voz»...);
las mandan las herramientas de herramientas/techo.py.
"""

import json
import math
import os
import random
import subprocess
import time

import cairo
import gi
import numpy as np

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, senales

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402
except (ValueError, ImportError):
    GtkLayerShell = None

ENCENDIDO = senales.CARPETA / "holograma"  # mientras se ve: «pid barras estilo»
_CAVA_CONF = senales.CARPETA / "holograma-cava.conf"
_TECHO = config.RAIZ / "techo.sh"

LIENZO = 800, 600  # se dibuja a este tamaño y se escala al del proyector
N_BARRAS = 48
CALIDAD = 0.6  # NAVI se dibuja más pequeña y se amplía: gasta la tercera parte (y brilla suave)

# Degradado del modo techo y los brillos del holograma
OSCURO = (0x1a / 255, 0x00 / 255, 0x33 / 255)
MORADO = (0x7b / 255, 0x2c / 255, 0xbf / 255)
LILA = (0xe0 / 255, 0xaa / 255, 0xff / 255)
ROSA = (0.88, 0.27, 0.48)
# Estilo «color»: el beige del arte conceptual (el mismo de la mascota)
BEIGE = (0.80, 0.76, 0.66)
BEIGE_BORDE = (0.36, 0.33, 0.28)
GRIS = (0.17, 0.17, 0.19)
NEGRO = (0.07, 0.07, 0.08)
PANTALLA = (0.05, 0.06, 0.09)
CABLE = (0.34, 0.34, 0.41)
AZUL = (0.62, 0.80, 1.0)
VERDE = (0.35, 0.85, 0.45)
ESTILOS = ("color", "lineas")


def _capsula(cr, a, b, ra: float, rb: float) -> None:
    """Un hueso con grosor: de a (radio ra) a b (radio rb), con puntas redondas."""
    angulo = math.atan2(b[1] - a[1], b[0] - a[0])
    cr.new_sub_path()
    cr.arc(a[0], a[1], ra, angulo + math.pi / 2, angulo + 3 * math.pi / 2)
    cr.arc(b[0], b[1], rb, angulo - math.pi / 2, angulo + math.pi / 2)
    cr.close_path()


def _brillar(cr, color, alfa: float, ancho: float = 1.6, relleno: float = 0.0,
             tapar: bool = False) -> None:
    """Traza el camino actual como luz: halo ancho y suave + línea fina brillante.
    `tapar` pinta antes de negro el interior, para que no se transparente lo de atrás."""
    if tapar:
        cr.set_source_rgb(0, 0, 0)
        cr.fill_preserve()
    if relleno:
        cr.set_source_rgba(*color, relleno * alfa)
        cr.fill_preserve()
    for grosor, fuerza in ((ancho * 5, 0.08), (ancho * 2.5, 0.22), (ancho, 1.0)):
        cr.set_line_width(grosor)
        cr.set_source_rgba(*color, fuerza * alfa)
        cr.stroke_preserve()
    cr.new_path()


def _hacia(origen, angulo: float, largo: float):
    """El punto a `largo` de `origen`; angulo 0 = hacia abajo, positivo = hacia afuera."""
    return origen[0] + math.sin(angulo) * largo, origen[1] + math.cos(angulo) * largo


class Holograma:
    def __init__(self, personaje, voz) -> None:
        self._personaje = personaje  # el de la esquina: de ahí sale su estado
        self._voz = voz
        self._ventana: Gtk.Window | None = None
        self._monitor = None
        self._cava: subprocess.Popen | None = None
        self._pendiente = b""
        self.barras_modo: str | None = None
        self.estilo = "color"  # "color" (beige, como el arte conceptual) o "lineas" (de luz)
        self._barras = np.zeros(N_BARRAS)
        self._inicio = time.monotonic()
        self._parpadeo = 0.0
        self._proximo_parpadeo = time.monotonic() + 3
        self._glitch = (0.0, 0)  # (cuándo empezó, semilla)
        self._proximo_glitch = time.monotonic() + 6
        self._boca = 0.0
        self._mano = 0.0  # cuánto levanta la mano derecha (al escuchar)
        self._temporizador = None
        self._ultimo_dibujo = 0.0
        self._figura_lista: cairo.ImageSurface | None = None
        self._figura_hora = 0.0
        Gdk.Display.get_default().connect("monitor-removed", self._monitor_quitado)

    @property
    def encendido(self) -> bool:
        return self._ventana is not None

    # --- encender, apagar

    def encender(self, salida: str) -> str:
        monitor = self._buscar_monitor(salida)
        if monitor is None:
            return f"No encuentro la pantalla {salida}."
        self.apagar(dejar_barras=True)
        self._monitor = monitor
        self._ventana = ventana = Gtk.Window(title="NAVI holograma")
        ventana.set_decorated(False)
        ventana.set_app_paintable(True)
        dibujo = Gtk.DrawingArea()
        dibujo.connect("draw", self._dibujar)
        ventana.add(dibujo)
        area = monitor.get_geometry()
        if GtkLayerShell is not None and GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(ventana)
            GtkLayerShell.set_namespace(ventana, "navi-holograma")
            GtkLayerShell.set_layer(ventana, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_monitor(ventana, monitor)
            for borde in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                          GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(ventana, borde, True)
            GtkLayerShell.set_exclusive_zone(ventana, -1)
        else:  # X11
            ventana.set_default_size(area.width, area.height)
            ventana.move(area.x, area.y)
            ventana.fullscreen()
        ventana.show_all()
        # Nadie hace clic en el techo: que los clics pasen de largo
        ventana.get_window().input_shape_combine_region(cairo.Region(), 0, 0)
        self._temporizador = GLib.timeout_add(50, self._animar, dibujo)  # 20 imágenes/s
        self._guardar_estado()
        return "ok"

    def apagar(self, dejar_barras: bool = False) -> None:
        if self._temporizador:
            GLib.source_remove(self._temporizador)
            self._temporizador = None
        if self._ventana is not None:
            self._ventana.destroy()
            self._ventana = None
        if not dejar_barras:
            self.barras(None)
        ENCENDIDO.unlink(missing_ok=True)

    def cambiar_estilo(self, estilo: str) -> None:
        if estilo in ESTILOS:
            self.estilo = estilo
            self._figura_lista = None  # que se note ya, sin esperar al próximo dibujo
            self._guardar_estado()

    def barras(self, modo: str | None) -> str:
        """Barras de audio a sus pies: "musica", "voz" o None para quitarlas."""
        if self._cava is not None:
            self._cava.terminate()
            self._cava = None
        self.barras_modo = None
        self._barras[:] = 0
        if modo:
            r = subprocess.run([str(_TECHO), "fuente", modo], capture_output=True, text=True)
            if r.returncode != 0:
                return r.stdout.strip() or "No pude escuchar el audio."
            _CAVA_CONF.write_text(_config_cava(r.stdout.strip()))
            self._cava = subprocess.Popen(["cava", "-p", str(_CAVA_CONF)],
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          stdin=subprocess.DEVNULL)
            os.set_blocking(self._cava.stdout.fileno(), False)
            GLib.io_add_watch(self._cava.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                              GLib.IO_IN | GLib.IO_HUP, self._leer_cava, self._cava)
            self.barras_modo = modo
        self._guardar_estado()
        return "ok"

    def _guardar_estado(self) -> None:
        if self.encendido:
            ENCENDIDO.write_text(f"{os.getpid()} {self.barras_modo or '-'} {self.estilo}\n")

    def _buscar_monitor(self, salida: str):
        """El monitor de GTK que es la salida `salida` de Sway (por su posición)."""
        try:
            r = subprocess.run(["swaymsg", "-t", "get_outputs", "-r"],
                               capture_output=True, text=True, timeout=5)
            rect = next(o["rect"] for o in json.loads(r.stdout) if o["name"] == salida)
        except (OSError, ValueError, StopIteration, subprocess.TimeoutExpired):
            return None
        pantalla = Gdk.Display.get_default()
        for i in range(pantalla.get_n_monitors()):
            monitor = pantalla.get_monitor(i)
            area = monitor.get_geometry()
            if (area.x, area.y) == (rect["x"], rect["y"]):
                return monitor
        return None

    def _monitor_quitado(self, _pantalla, monitor) -> None:
        # Si desconectan el proyector, no queremos un negro gigante sobre la laptop
        if monitor == self._monitor:
            self.apagar()

    def _leer_cava(self, fd, condicion, proceso) -> bool:
        if proceso is not self._cava:
            return False
        if condicion & GLib.IO_HUP:
            return False
        try:
            self._pendiente += os.read(fd, 65536)
        except BlockingIOError:
            return True
        *lineas, self._pendiente = self._pendiente.split(b"\n")
        if lineas:
            valores = [v for v in lineas[-1].split(b";") if v]
            if len(valores) == N_BARRAS:
                self._barras = np.array([int(v) for v in valores]) / 1000
        return True

    # --- animación

    def _animar(self, dibujo) -> bool:
        ahora = time.monotonic()
        if ahora >= self._proximo_parpadeo:
            self._parpadeo = ahora
            self._proximo_parpadeo = ahora + random.uniform(2.5, 6)
        if ahora >= self._proximo_glitch:
            self._glitch = (ahora, random.randrange(1 << 30))
            self._proximo_glitch = ahora + random.uniform(5, 14)
        estado = self._personaje.estado
        abierta = self._voz.volumen() if estado == "hablando" else 0.0
        self._boca += (abierta - self._boca) * 0.5
        self._mano += ((1.0 if estado == "escuchando" else 0.0) - self._mano) * 0.12
        movida = (estado != "reposo" or self.barras_modo or self._mano > 0.02
                  or ahora - self._glitch[0] < 0.2 or ahora - self._parpadeo < 0.2)
        if movida or ahora - self._ultimo_dibujo > 1 / 10:
            self._ultimo_dibujo = ahora
            dibujo.queue_draw()
        return True

    def _dibujar(self, widget, cr) -> bool:
        t = time.monotonic() - self._inicio
        ancho, alto = widget.get_allocated_width(), widget.get_allocated_height()
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        escala = min(ancho / LIENZO[0], alto / LIENZO[1])
        cr.translate((ancho - LIENZO[0] * escala) / 2, (alto - LIENZO[1] * escala) / 2)
        cr.scale(escala, escala)

        if self.barras_modo:
            self._dibujar_barras(cr)
        else:
            self._base(cr, t)

        # La figura se dibuja aparte (y solo 10 veces por segundo: es lo que más
        # gasta) para poder «glitchearla»; las barras sí van a 20 por segundo.
        if self._figura_lista is None or time.monotonic() - self._figura_hora > 1 / 10:
            self._figura_lista = self._pintar_figura(t)
            self._figura_hora = time.monotonic()
        figura = cairo.SurfacePattern(self._figura_lista)
        ampliar = cairo.Matrix()
        ampliar.scale(CALIDAD, CALIDAD)
        figura.set_matrix(ampliar)
        figura.set_filter(cairo.FILTER_GOOD)
        dormida = self._personaje.dormida
        alfa = (0.45 if dormida else 0.9) + 0.06 * math.sin(t * 7.3) + random.uniform(-0.03, 0.03)
        inicio_glitch, semilla = self._glitch
        if time.monotonic() - inicio_glitch < 0.18:
            azar = random.Random(semilla)
            for _ in range(5):  # franjas desplazadas
                y, alto_franja = azar.uniform(40, 520), azar.uniform(6, 30)
                cr.save()
                cr.rectangle(0, y, LIENZO[0], alto_franja)
                cr.clip()
                cr.translate(azar.uniform(-18, 18), 0)
                cr.set_source(figura)
                cr.paint_with_alpha(alfa)
                cr.restore()
            cr.set_source(figura)
            cr.paint_with_alpha(alfa * 0.35)
        else:
            cr.set_source(figura)
            cr.paint_with_alpha(alfa)
        return False

    def _pintar_figura(self, t: float) -> cairo.ImageSurface:
        """NAVI con sus scanlines y la franja de luz, solo sobre su figura."""
        superficie = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(LIENZO[0] * CALIDAD),
                                        int(LIENZO[1] * CALIDAD))
        cr = cairo.Context(superficie)
        cr.scale(CALIDAD, CALIDAD)
        cr.set_tolerance(0.6)  # curvas con menos tramos: casi igual de bonitas, mucho más rápidas
        self._figura(cr, t)
        cr.set_operator(cairo.OPERATOR_DEST_OUT)  # rayas: le quitan luz a la figura
        cr.set_source_rgba(0, 0, 0, 0.35)
        for y in range(0, 560, 3):
            cr.rectangle(0, y, LIENZO[0], 1)
        cr.fill()
        cr.set_operator(cairo.OPERATOR_ATOP)  # una franja de luz que la recorre despacio
        banda = (t * 90) % 700 - 100
        cr.set_source(_degradado(0, banda - 30, 0, banda + 30,
                                 [(0, LILA, 0), (0.5, LILA, 0.35), (1, LILA, 0)]))
        cr.rectangle(0, banda - 30, LIENZO[0], 60)
        cr.fill()
        return superficie

    def _base(self, cr, t: float) -> None:
        """Sin barras: el anillo del proyector de hologramas bajo sus pies."""
        pulso = 0.5 + 0.5 * math.sin(t * 2)
        for i, radio in enumerate((150, 110, 70)):
            cr.save()
            cr.translate(400, 545)
            cr.scale(1, 0.18)
            cr.arc(0, 0, radio + pulso * 6, 0, 2 * math.pi)
            cr.restore()
            _brillar(cr, MORADO if i else LILA, 0.4 + 0.3 * pulso, 1.4)
        degradado = _degradado(0, 545, 0, 150, [(0, MORADO, 0.22), (1, MORADO, 0)])
        cr.set_source(degradado)
        cr.move_to(250, 545)
        cr.line_to(330, 150)
        cr.line_to(470, 150)
        cr.line_to(550, 545)
        cr.fill()

    def _dibujar_barras(self, cr) -> None:
        izquierda, derecha, suelo, maximo = 40, 760, 590, 120
        paso = (derecha - izquierda) / N_BARRAS
        degradado = _degradado(0, suelo, 0, suelo - maximo,
                               [(0, OSCURO, 1), (0.5, MORADO, 1), (1, LILA, 1)])
        for i, valor in enumerate(self._barras):
            alto = max(2.0, valor * maximo)
            cr.rectangle(izquierda + i * paso + 1.5, suelo - alto, paso - 3, alto)
        cr.set_source(degradado)
        cr.fill()

    # --- NAVI (según el arte conceptual RETRO-UNIT-01: monitor de cabeza, torre de mochila)

    def _pieza(self, cr, tono: str) -> None:
        """Rellena y perfila el camino actual según el estilo (color o líneas)."""
        if self.estilo == "lineas":
            color, relleno = {"beige": (LILA, 0.10), "oscuro": (MORADO, 0.35),
                              "pantalla": (MORADO, 0.0)}[tono]
            _brillar(cr, color, 1.0 if tono != "beige" else 0.95, 1.4, relleno, tapar=True)
            return
        relleno, borde = {"beige": (BEIGE, BEIGE_BORDE), "oscuro": (GRIS, NEGRO),
                          "pantalla": (PANTALLA, NEGRO)}[tono]
        cr.set_source_rgb(*relleno)
        cr.fill_preserve()
        cr.set_source_rgb(*borde)
        cr.set_line_width(1.4)
        cr.stroke()

    def _detalle(self, cr, ancho: float = 1.1) -> None:
        """Rayitas encima de una pieza: rejillas, ranuras, juntas de las placas."""
        if self.estilo == "lineas":
            _brillar(cr, MORADO, 0.85, ancho)
        else:
            cr.set_source_rgb(*BEIGE_BORDE)
            cr.set_line_width(ancho)
            cr.stroke()

    def _cable(self, cr, ancho: float = 3.5) -> None:
        if self.estilo == "lineas":
            _brillar(cr, MORADO, 0.7, ancho * 0.45)
        else:
            cr.set_source_rgb(*CABLE)
            cr.set_line_width(ancho)
            cr.stroke()

    def _luz(self, cr, color, alfa: float = 1.0) -> None:
        """Pixeles y lucecitas (cara, LEDs): en estilo líneas, todo es lila."""
        cr.set_source_rgba(*(LILA if self.estilo == "lineas" and color != VERDE else color), alfa)
        cr.fill()

    def _figura(self, cr, t: float) -> None:
        estado = self._personaje.estado
        graves = float(self._barras[:8].mean()) if self.barras_modo else 0.0
        flota = math.sin(t * 1.3) * 7 - graves * 10  # sube y baja; con música, «baila»
        cr.save()
        cr.translate(400, 178 + flota)
        cr.scale(1.08, 1.08)

        respira = math.sin(t * 2.1) * 1.2
        inclina = 0.12 if estado == "escuchando" else 0.03 * math.sin(t * 0.7) + graves * 0.08
        hablar = self._boca if estado == "hablando" else 0.0
        hombros = (-46, 12 + respira * 0.3), (46, 12 + respira * 0.3)
        caderas = (-17, 132), (17, 132)

        # El esqueleto: dónde queda cada articulación en esta imagen
        brazos = []
        for lado, hombro in ((-1, hombros[0]), (1, hombros[1])):
            if lado > 0 and self._mano > 0.02:  # escuchando: mano al lado del monitor
                m = self._mano
                codo = _hacia(hombro, 0.14 + m * 1.5, 62)
                oreja = (58 + inclina * 40, -66)
                hacia_oreja = math.atan2(oreja[0] - codo[0], oreja[1] - codo[1])
                muneca = _hacia(codo, 0.08 * (1 - m) + hacia_oreja * m, 52)
            elif estado == "hablando":  # gesticula: manos delante del pecho
                gesto = math.sin(t * 3.1 + lado * 1.7) * 0.25 + hablar * 0.25
                codo = _hacia(hombro, lado * (0.22 + gesto * 0.3), 62)
                muneca = _hacia(codo, -lado * (1.9 + gesto), 52)
            else:
                balanceo = math.sin(t * 1.3 + lado) * 0.04
                codo = _hacia(hombro, lado * (0.12 + balanceo), 62)
                muneca = _hacia(codo, lado * (0.06 + balanceo), 56)
            brazos.append((lado, hombro, codo, muneca))

        self._cables_del_nexo(cr, t, estado)
        self._torre(cr, t)

        # Piernas (flotando: puntas hacia abajo, una rodilla un poco doblada)
        for lado, cadera in ((-1, caderas[0]), (1, caderas[1])):
            dobla = 0.2 if lado < 0 else 0.06
            rodilla = _hacia(cadera, -lado * 0.03 + math.sin(t * 1.1 + lado) * 0.02, 70)
            tobillo = _hacia(rodilla, -dobla, 66)
            punta = _hacia(tobillo, -dobla * 1.4 + lado * 0.06, 20)
            _capsula(cr, rodilla, tobillo, 12, 8)
            self._pieza(cr, "beige")
            _capsula(cr, tobillo, punta, 9, 4)  # bota
            self._pieza(cr, "beige")
            _capsula(cr, cadera, rodilla, 16, 12)
            self._pieza(cr, "beige")
            _capsula(cr, _hacia(cadera, 0, 26), _hacia(cadera, 0, 52), 12, 10)
            self._detalle(cr, 0.9)  # junta de la placa del muslo
            cr.arc(rodilla[0], rodilla[1], 10, 0, 2 * math.pi)  # rodillera negra
            self._pieza(cr, "oscuro")
            cr.arc(rodilla[0], rodilla[1], 6, 0, 2 * math.pi)
            self._pieza(cr, "beige")

        # Cadera y abdomen negro con rejillas (las «cooling vents»)
        cr.move_to(-30, 104)
        cr.line_to(30, 104)
        cr.line_to(32, 128)
        cr.curve_to(20, 142, 8, 146, 0, 146)
        cr.curve_to(-8, 146, -20, 142, -32, 128)
        cr.close_path()
        self._pieza(cr, "beige")
        _rectangulo(cr, -27, 54, 54, 54, 6)
        self._pieza(cr, "oscuro")
        for y in range(60, 104, 5):
            cr.move_to(-25, y)
            cr.line_to(-15, y)
            cr.move_to(15, y)
            cr.line_to(25, y)
        if self.estilo == "lineas":
            _brillar(cr, MORADO, 0.7, 0.9)
        else:
            cr.set_source_rgb(*NEGRO)
            cr.set_line_width(1.6)
            cr.stroke()
        # El frente de la torre en la barriga: bahías y su LED verde
        _rectangulo(cr, -12, 58, 24, 46, 3)
        self._pieza(cr, "beige")
        for y in (64, 72):
            cr.rectangle(-9, y, 18, 5)
        self._detalle(cr, 0.9)
        cr.arc(7, 96, 1.8, 0, 2 * math.pi)
        self._luz(cr, VERDE, 0.6 + 0.4 * (math.sin(t * 5) > 0))

        # Pecho: placa beige con hombros anchos
        cr.move_to(-44, 6 + respira * 0.3)
        cr.curve_to(-46, 30, -38, 50, -27, 58)
        cr.line_to(27, 58)
        cr.curve_to(38, 50, 46, 30, 44, 6 + respira * 0.3)
        cr.curve_to(24, -4, -24, -4, -44, 6 + respira * 0.3)
        self._pieza(cr, "beige")
        cr.move_to(-30, 22)
        cr.curve_to(-14, 30, 14, 30, 30, 22)  # la juntura de las placas
        cr.move_to(0, 28)
        cr.line_to(0, 56)
        self._detalle(cr)

        # Brazos (el de la torre lleva el teclado en el antebrazo)
        for lado, hombro, codo, muneca in brazos:
            direccion = math.atan2(muneca[0] - codo[0], muneca[1] - codo[1])
            mano = _hacia(muneca, direccion, 12)
            _capsula(cr, hombro, codo, 9, 7)
            self._pieza(cr, "beige")
            _capsula(cr, codo, muneca, 8, 6)
            self._pieza(cr, "beige")
            if lado > 0:
                self._teclado_del_brazo(cr, codo, muneca)
            _capsula(cr, muneca, mano, 6, 5)  # mano mecánica
            self._pieza(cr, "beige")
            cr.move_to(*_hacia(muneca, direccion, 4))
            cr.line_to(*mano)
            self._detalle(cr, 0.8)
            cr.arc(codo[0], codo[1], 6, 0, 2 * math.pi)  # codo negro
            self._pieza(cr, "oscuro")
            cr.save()
            cr.translate(*hombro)
            cr.scale(1, 0.9)
            cr.arc(0, 0, 15, 0, 2 * math.pi)  # hombrera
            cr.restore()
            self._pieza(cr, "beige")
            cr.arc(hombro[0] + lado * 2, hombro[1] - 2, 9, math.pi * 1.1, math.pi * 1.9)
            self._detalle(cr, 0.9)

        # El cable que baja de la torre y se mete en el brazo del teclado
        _, _, codo, _ = brazos[1]
        cr.move_to(58, 40)
        cr.curve_to(76, 60, codo[0] + 20, codo[1] - 10, codo[0] + 4, codo[1])
        self._cable(cr, 3)

        # Cuello negro en anillos y la cabeza (el monitor)
        _rectangulo(cr, -8, -18, 16, 20, 3)
        self._pieza(cr, "oscuro")
        for y in (-12, -6):
            cr.move_to(-8, y)
            cr.line_to(8, y)
        self._detalle(cr, 0.9)
        cr.save()
        cr.translate(0, -16)
        cr.rotate(inclina)
        cr.scale(1.3, 1.3)  # cabeza grande, como en el arte conceptual
        self._cabeza(cr, t, estado, hablar)
        cr.restore()
        cr.restore()

    def _teclado_del_brazo(self, cr, codo, muneca) -> None:
        angulo = math.atan2(muneca[1] - codo[1], muneca[0] - codo[0])
        largo = math.dist(codo, muneca)
        cr.save()
        cr.translate(*codo)
        cr.rotate(angulo)
        _rectangulo(cr, 8, -6, largo - 14, 12, 2)
        self._pieza(cr, "beige")
        for fila in (-4.5, 0.5):
            for x in range(10, int(largo) - 8, 6):
                cr.rectangle(x, fila, 4.5, 4)
        self._detalle(cr, 0.7)
        cr.restore()

    def _torre(self, cr, t: float) -> None:
        """La torre del PC, de mochila sobre el hombro, con su disquetera y LEDs."""
        cr.move_to(16, -8)
        cr.line_to(56, -14)
        cr.line_to(64, -6)
        cr.line_to(64, 82)
        cr.line_to(24, 88)
        cr.line_to(16, 80)
        cr.close_path()
        self._pieza(cr, "beige")
        cr.move_to(56, -14)
        cr.line_to(56, 74)
        cr.line_to(64, 82)
        cr.move_to(56, 74)
        cr.line_to(16, 80)
        self._detalle(cr, 0.9)
        for y in (2, 12):
            cr.move_to(22, y + 4)
            cr.line_to(50, y)
        self._detalle(cr, 1.4)  # bahías
        cr.arc(48, 56, 1.8, 0, 2 * math.pi)
        self._luz(cr, VERDE, 0.6 + 0.4 * (math.sin(t * 3.7) > 0))
        cr.arc(48, 62, 1.8, 0, 2 * math.pi)
        self._luz(cr, ROSA, 0.5 + 0.5 * random.random())  # el disco duro trabajando

    def _cables_del_nexo(self, cr, t: float, estado: str) -> None:
        """Cables que salen de la torre y suben fuera de la imagen, hacia el Nexo."""
        for i, (x, y, arriba) in enumerate(((26, -10, 120), (40, -12, 230),
                                             (52, -13, 330), (-4, -16, -150))):
            vaiven = math.sin(t * 0.9 + i) * 16
            cr.move_to(x, y)
            cr.curve_to(x + vaiven, y - 70, arriba + vaiven, -150, arriba * 0.8, -260)
            self._cable(cr)
            if estado == "pensando":  # datos que suben por los cables
                for k in range(3):
                    f = (t * 0.8 + k / 3 + i * 0.13) % 1
                    px = _bezier(x, x + vaiven, arriba + vaiven, arriba * 0.8, f)
                    py = _bezier(y, y - 70, -150, -260, f)
                    cr.arc(px, py, 2.5, 0, 2 * math.pi)
                    self._luz(cr, AZUL)

    def _cabeza(self, cr, t: float, estado: str, hablar: float) -> None:
        """La cabeza: un monitor CRT con visera, y la cara pixelada en la pantalla."""
        cr.move_to(-30, -86)  # la parte de atrás del tubo, en perspectiva
        cr.line_to(30, -86)
        cr.line_to(40, -72)
        cr.line_to(40, -14)
        cr.line_to(-40, -14)
        cr.close_path()
        self._pieza(cr, "beige")
        _rectangulo(cr, -44, -80, 88, 70, 7)  # el marco
        self._pieza(cr, "beige")
        cr.move_to(-48, -80)  # la visera retráctil
        cr.line_to(46, -80)
        cr.line_to(40, -90)
        cr.line_to(-40, -92)
        cr.close_path()
        self._pieza(cr, "oscuro")
        for x in range(-38, -22, 4):  # rejilla y LED del marco
            cr.rectangle(x, -17, 2, 4)
        self._detalle(cr, 0.8)
        cr.arc(36, -15, 1.8, 0, 2 * math.pi)
        self._luz(cr, VERDE)

        _rectangulo(cr, -36, -74, 72, 52, 5)
        self._pieza(cr, "pantalla")
        if estado == "escuchando":  # pantalla rosita mientras te oye, como la mascota
            _rectangulo(cr, -35, -73, 70, 50, 5)
            cr.set_source_rgba(*ROSA, 0.18 + 0.08 * math.sin(t * 6))
            cr.fill()
        self._cara(cr, t, estado, hablar)

    def _cara(self, cr, t: float, estado: str, hablar: float) -> None:
        """Cara de pixeles, como en la hoja de expresiones."""
        reaccion = self._personaje._reaccion[0] if self._personaje._reaccion else ""
        dormida = self._personaje.dormida
        parpadeo = time.monotonic() - self._parpadeo < 0.15
        color = AZUL

        if reaccion == "mareo":  # «Overwhelmed»: pixeles sueltos y boca en zigzag
            for x, y in ((-16, -64), (-6, -58), (8, -64), (16, -56), (-12, -52), (2, -66)):
                cr.rectangle(x - 3, y - 3, 6, 6)
            self._luz(cr, color)
            for k in range(6):
                cr.rectangle(-12 + k * 4, -38 - (2 if k % 2 else 0), 3, 3)
            self._luz(cr, color)
            return

        # Ojos
        for lado in (-1, 1):
            cx, cy = lado * 13, -56
            if dormida or parpadeo:
                cr.rectangle(cx - 5, cy, 10, 3)
            elif estado == "pensando":  # «Pensive»: miran a un lado, medio cerrados
                cr.rectangle(cx - 1, cy - 4, 9, 5)
            elif estado == "escuchando":  # ojos grandes: te está oyendo
                cr.rectangle(cx - 5.5, cy - 6, 11, 11)
            else:
                cr.rectangle(cx - 4.5, cy - 5, 9, 9)
            self._luz(cr, color)

        # Boca
        if dormida:
            for i, (x, y) in enumerate(((20, -66), (25, -71), (30, -76))):  # zzz
                cr.rectangle(x, y, 3 + i, 3 + i)
            self._luz(cr, color, 0.5 + 0.5 * math.sin(t * 2))
            cr.rectangle(-5, -38, 10, 3)
        elif estado == "hablando":
            alto = 3 + hablar * 9
            cr.rectangle(-8, -40 - alto / 2, 16, alto)
        elif estado == "escuchando":  # ondas de sonido en la boca
            for k in range(5):
                alto = 3 + abs(math.sin(t * 9 + k * 1.3)) * 7
                cr.rectangle(-11 + k * 5, -39 - alto / 2, 3, alto)
        elif estado == "pensando":
            cr.rectangle(-6, -38, 12, 3)
            for k in range(3):  # puntitos de «cargando»
                if int(t * 3) % 4 > k:
                    cr.rectangle(18 + k * 5, -30, 3, 3)
        else:  # «Happy»: sonrisa de pixeles
            for x, y in ((-9, -42), (-6, -39), (-3, -38), (0, -38), (3, -39), (6, -42)):
                cr.rectangle(x, y, 3, 3)
        self._luz(cr, color)


def _rectangulo(cr, x: float, y: float, ancho: float, alto: float, radio: float) -> None:
    cr.new_sub_path()
    cr.arc(x + ancho - radio, y + radio, radio, -math.pi / 2, 0)
    cr.arc(x + ancho - radio, y + alto - radio, radio, 0, math.pi / 2)
    cr.arc(x + radio, y + alto - radio, radio, math.pi / 2, math.pi)
    cr.arc(x + radio, y + radio, radio, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _bezier(a: float, b: float, c: float, d: float, f: float) -> float:
    g = 1 - f
    return g ** 3 * a + 3 * g * g * f * b + 3 * g * f * f * c + f ** 3 * d


def _degradado(x0, y0, x1, y1, paradas):
    degradado = cairo.LinearGradient(x0, y0, x1, y1)
    for posicion, color, alfa in paradas:
        degradado.add_color_stop_rgba(posicion, *color, alfa)
    return degradado


def _config_cava(fuente: str) -> str:
    return f"""[general]
bars = {N_BARRAS}
framerate = 20

[input]
method = pulse
source = {fuente}

[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10
channels = mono
"""

