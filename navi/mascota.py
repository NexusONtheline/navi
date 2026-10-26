"""NAVI como mascota de escritorio: un monitorcito en la esquina con un globo de diálogo.

`navi --mascota` la deja siempre visible. Clic en ella para escribirle (Enter vacío
o el botón del micrófono para hablarle), clic derecho para el menú. También despierta
con «NAVI, actívate» y con Super+N (`navi --abrir`).

En Sway (Wayland) usa gtk-layer-shell para quedarse pegada a la esquina por encima
de las ventanas; en escritorios X11 (Cinnamon, XFCE...) es una ventana sin bordes
siempre encima. GTK hace todo en un solo hilo: lo lento (Gemini, Whisper) va en
un hilo aparte que le pasa los cambios con GLib.idle_add.
"""

import math
import queue
import random
import re
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

ANCHO, ALTO = 120, 132  # lienzo del personaje
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

class Personaje(Gtk.DrawingArea):
    """Un monitor CRT flotante con cara, del que cuelga un cable del Nexo."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(ANCHO, ALTO)
        self.estado = "reposo"  # reposo · escuchando · pensando · hablando
        self._inicio = time.monotonic()
        self._parpadeo = 0.0  # momento en que empezó el último parpadeo
        self._proximo_parpadeo = time.monotonic() + 3
        self._mirada = (0.0, 0.0)
        self._ultimo_dibujo = 0.0
        self.connect("draw", self._dibujar)
        GLib.timeout_add(80, self._animar)

    def _animar(self) -> bool:
        ahora = time.monotonic()
        # En reposo basta con 4 imágenes por segundo (gasta menos CPU); activa, 12
        if self.estado == "reposo" and ahora - self._parpadeo > 0.2 \
                and ahora - self._ultimo_dibujo < 0.25:
            return True
        self._ultimo_dibujo = ahora
        if ahora >= self._proximo_parpadeo:
            self._parpadeo = ahora
            self._proximo_parpadeo = ahora + random.uniform(2.5, 6)
            if self.estado == "reposo" and random.random() < 0.4:
                self._mirada = (random.uniform(-3, 3), random.uniform(-1.5, 1.5))
        self.queue_draw()
        return True

    def _dibujar(self, _widget, cr) -> bool:
        t = time.monotonic() - self._inicio
        cr.set_operator(0)  # CLEAR: fondo transparente
        cr.paint()
        cr.set_operator(2)  # OVER

        flota = math.sin(t * 1.6) * 2.5
        x, y, ancho, alto = 18, 10 + flota, 84, 68

        self._cable(cr, t, x, y + alto)

        # Sombra brillante bajo el monitor
        cr.save()
        cr.translate(60, ALTO - 8)
        cr.scale(1, 0.25)
        cr.arc(0, 0, 30 - flota, 0, 2 * math.pi)
        r, g, b = ROSA if self.estado == "escuchando" else AZUL
        cr.set_source_rgba(r, g, b, 0.18)
        cr.fill()
        cr.restore()

        # Carcasa
        _rectangulo(cr, x, y, ancho, alto, 10)
        cr.set_source_rgb(0.10, 0.10, 0.14)
        cr.fill_preserve()
        cr.set_source_rgb(0.25, 0.25, 0.32)
        cr.set_line_width(1.5)
        cr.stroke()
        # Patita
        cr.rectangle(52, y + alto, 16, 6)
        cr.set_source_rgb(0.18, 0.18, 0.24)
        cr.fill()

        # Pantalla
        px, py, pancho, palto = x + 7, y + 7, ancho - 14, alto - 18
        _rectangulo(cr, px, py, pancho, palto, 6)
        cr.set_source_rgb(0.03, 0.04, 0.06)
        cr.fill()
        color = ROSA if self.estado == "escuchando" else AZUL
        # Líneas de barrido
        cr.set_source_rgba(*color, 0.06)
        for linea in range(int(py), int(py + palto), 3):
            cr.rectangle(px, linea, pancho, 1)
        cr.fill()
        if self.estado == "pensando":  # una franja que recorre la pantalla
            franja = py + (t * 40) % palto
            cr.set_source_rgba(*color, 0.15)
            cr.rectangle(px, franja, pancho, 4)
            cr.fill()

        self._cara(cr, t, px + pancho / 2, py + palto / 2, color)

        # Lucecita de encendido
        cr.arc(x + ancho - 10, y + alto - 5.5, 1.8, 0, 2 * math.pi)
        encendida = self.estado != "reposo" and int(t * 4) % 2
        cr.set_source_rgb(*(ROSA if encendida else (0.2, 0.5, 0.3)))
        cr.fill()

        if self.estado == "escuchando":
            self._ondas(cr, t, x + ancho + 2, y + alto / 2)
        return False

    def _cara(self, cr, t: float, cx: float, cy: float, color) -> None:
        mx, my = self._mirada
        if self.estado == "pensando":
            mx, my = 3 * math.sin(t * 2), -3
        elif self.estado != "reposo":
            mx, my = 0, 0
        # Parpadeo: los ojos se cierran durante 0.15 s
        avance = time.monotonic() - self._parpadeo
        abierto = 1.0 if avance > 0.15 else abs(avance / 0.075 - 1)
        alto_ojo = 12 if self.estado == "escuchando" else 10
        for lado in (-1, 1):
            cr.save()
            cr.translate(cx + lado * 13 + mx, cy - 3 + my)
            cr.scale(1, max(0.12, abierto))
            _rectangulo(cr, -4, -alto_ojo / 2, 8, alto_ojo, 3)
            cr.restore()
        cr.set_source_rgba(*color, 0.95)
        cr.fill()

        # Boca: una línea que se abre al hablar
        boca = 0.0
        if self.estado == "hablando":
            boca = abs(math.sin(t * 11)) * 4 + abs(math.sin(t * 7)) * 2
        cr.save()
        cr.translate(cx + mx * 0.5, cy + 11 + my * 0.5)
        if boca > 0.5:
            cr.scale(1, boca / 6)
            cr.arc(0, 0, 6, 0, 2 * math.pi)
            cr.restore()
            cr.fill()
        else:
            cr.restore()
            cr.set_line_width(1.6)
            cr.move_to(cx - 5 + mx * 0.5, cy + 11 + my * 0.5)
            cr.line_to(cx + 5 + mx * 0.5, cy + 11 + my * 0.5)
            cr.stroke()

    def _cable(self, cr, t: float, x: float, y: float) -> None:
        """Los cables del Nexo, colgando y meciéndose."""
        for i, (grosor, desfase) in enumerate(((2.2, 0.0), (1.4, 1.7))):
            vaiven = math.sin(t * 1.1 + desfase) * 6
            inicio = x + 10 + i * 7
            cr.move_to(inicio, y - 4)
            cr.curve_to(inicio - 10 + vaiven, y + 20, inicio - 22 - vaiven, y + 30,
                        inicio - 16 + vaiven, ALTO)
            cr.set_source_rgba(0.42, 0.42, 0.52, 0.9)
            cr.set_line_width(grosor)
            cr.stroke()

    def _ondas(self, cr, t: float, x: float, y: float) -> None:
        """Ondas que salen del monitor mientras te escucha."""
        cr.set_line_width(1.5)
        for i in range(3):
            fase = (t * 1.5 + i / 3) % 1
            cr.arc(x - 6, y, 6 + fase * 12, -0.6, 0.6)
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
        evento.connect("button-press-event", self._clic)
        self.ventana.add(evento)
        self.ventana.show_all()

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
        if evento.button == 3:
            self._menu(evento)
        elif evento.button == 1:
            if self.personaje.estado == "escuchando":
                self.oido.parar.set()
            elif self.voz.hablando:
                self.voz.callar()
            elif self.globo.escribiendo:
                self.globo.ocultar()
            else:
                self.globo.escribir()
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
