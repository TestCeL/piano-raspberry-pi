#!/usr/bin/env python3
"""Toca el piano con el teclado de computador conectado a la Raspberry Pi y contrólalo desde la consola.

Lee el teclado directamente (evdev, eventos reales de pulsar/soltar), lo captura en exclusiva para que lo
tecleado no llegue a la consola (todas sus interfaces con letras: muchos teclados mecánicos envían a partir de la
7.ª tecla simultánea por una segunda interfaz), y envía MIDI por un puerto ALSA propio ("Teclado Piano:notas"), que el
enrutador del motor (enrutador_midi.py) mezcla con los teclados MIDI elegidos. Interfaz curses a pantalla
completa (sin X): teclado de 4 octavas, estado, sonido (instrumento), entradas MIDI y controles. Sin
dependencias externas.

Teclas (posición física; nombres de la distribución US):
  A W S E D F T G Y H U J K O L P Ñ(;) {(')  ->  do do# re re# mi fa fa# sol sol# la la# si do ...
  Z / X  octava -/+     C / V  fuerza -/+     ESPACIO  pedal     ESC  salir
  Flechas arriba/abajo  volumen de la G1     Flechas derecha/izquierda  reverb
  F1 / F2  transposición -/+   F3 curva de fuerza   F4 latencia   F5 conectar teclados nuevos sí/no
  F6 / F7  instrumento anterior / siguiente (se carga al soltar unos instantes; mientras carga, el piano queda
           en pausa y se muestra una ventana con el progreso)
  F9       menú de sonidos por categorías: flechas izq/der categoría, arriba/abajo instrumento, ENTER cargar,
           letras para buscar (RETROCESO borra), F9 o ESC cierra sin cambiar
  F10      salida de audio (tarjeta de sonido)
  F12      apagar la Raspberry Pi: pide confirmar (S sí, N o ESC no); sale con el código 10 y piano-teclado.sh
           cierra el piano y la apaga
  TAB  elegir entrada MIDI     ENTER  activar/desactivar la entrada elegida
  RETROCESO  silencio inmediato (apaga todas las notas)

Uso: teclado_piano.py [--dispositivo RUTA] [--octava N] [--fuerza N] [--sin-captura] [--interfaz MODO]
     teclado_piano.py --entrada-prueba ARCHIVO  (eventos evdev grabados; para pruebas)
"""
import argparse
import glob
import json
import math
import os
import re
import struct
import sys
import time
import unicodedata

import catalogo_instrumentos as cat

# --- Códigos evdev (linux/input-event-codes.h) -------------------------------------------
EV_KEY = 1
KEY_ESC, KEY_SPACE, KEY_TAB, KEY_ENTER, KEY_BACKSPACE = 1, 57, 15, 28, 14
KEY_Z, KEY_X, KEY_C, KEY_V = 44, 45, 46, 47
KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT = 103, 108, 105, 106
KEY_F1, KEY_F2, KEY_F3, KEY_F4, KEY_F5, KEY_F6, KEY_F7 = 59, 60, 61, 62, 63, 64, 65
KEY_F9, KEY_F10, KEY_F12 = 67, 68, 88
KEY_S, KEY_N = 31, 49
CODIGO_APAGAR = 10        # código de salida cuando se confirma F12 (piano-teclado.sh apaga la Pi)
# Teclas que escriben en la búsqueda del menú (posición física, distribución US; ";" es la Ñ en español)
LETRAS = {16: "q", 17: "w", 18: "e", 19: "r", 20: "t", 21: "y", 22: "u", 23: "i", 24: "o", 25: "p",
          30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h", 36: "j", 37: "k", 38: "l", 39: "ñ",
          44: "z", 45: "x", 46: "c", 47: "v", 48: "b", 49: "n", 50: "m", 57: " ",
          2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0"}
NOTAS_POR_TECLA = {  # código evdev -> semitonos desde el do de la octava actual
    30: 0,   # A  do
    17: 1,   # W  do#
    31: 2,   # S  re
    18: 3,   # E  re#
    32: 4,   # D  mi
    33: 5,   # F  fa
    20: 6,   # T  fa#
    34: 7,   # G  sol
    21: 8,   # Y  sol#
    35: 9,   # H  la
    22: 10,  # U  la#
    36: 11,  # J  si
    37: 12,  # K  do
    24: 13,  # O  do#
    38: 14,  # L  re
    25: 15,  # P  re#
    39: 16,  # ;  (Ñ en teclados en español) mi
    40: 17,  # '  ({ o ´ en teclados en español) fa
}
ETIQUETA = {30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K", 38: "L", 39: "Ñ",
            40: "{", 17: "W", 18: "E", 20: "T", 21: "Y", 22: "U", 24: "O", 25: "P"}
ORDENES_TECLA = {KEY_F1: "transponer -1", KEY_F2: "transponer +1", KEY_F3: "curva siguiente",
                 KEY_F4: "latencia siguiente", KEY_F5: "auto",
                 KEY_F6: "instrumento anterior", KEY_F7: "instrumento siguiente"}
FUERZAS = (16, 32, 48, 64, 80, 96, 112, 127)
OCTAVA_MIN, OCTAVA_MAX = 0, 7
NOTA_MIN, NOTA_MAX = 21, 108          # rango del piano (La0..Do8)
NOMBRES = ("Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si")
NOMBRES_CORTOS = ("Do", "", "Re", "", "Mi", "Fa", "", "So", "", "La", "", "Si")
RATE = 44100

# Formato de struct input_event en 64 bits: timeval (2 × long), type (u16), code (u16), value (s32)
FORMATO_EVDEV = "llHHi"
TAM_EVDEV = struct.calcsize(FORMATO_EVDEV)
EVIOCGRAB = 0x40044590


def nombre_nota(n):
    return f"{NOMBRES[n % 12]}{n // 12 - 1}"


def normalizar(texto):
    """Minúsculas y sin tildes, para buscar («organo» encuentra «Órganos»)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(ch) != "Mn")


class MenuInstrumentos:
    """Menú de sonidos por categorías (F9). Sin E/S: recibe teclas y devuelve acciones para el enrutador.
    Con texto de búsqueda muestra los instrumentos (de cualquier categoría) cuyo nombre o categoría lo contienen."""
    MAX_FILTRO = 20

    def __init__(self):
        self.abierto = False
        self.lista = []                 # [{"id", "nombre", "tipo"}] publicada por el enrutador
        self.actual = None
        self.cat = self.idx = 0
        self.filtro = ""

    def categorias(self):
        """[(tipo, nombre visible, [instrumentos])] en el orden del catálogo; solo las que tienen instrumentos."""
        return [(t, n, [i for i in self.lista if i.get("tipo") == t]) for t, n in cat.CATEGORIAS
                if any(i.get("tipo") == t for i in self.lista)]

    def visibles(self):
        if self.filtro:
            f = normalizar(self.filtro.strip())
            return [i for i in self.lista if f in normalizar(i.get("nombre", ""))
                    or f in normalizar(cat.NOMBRE_CATEGORIA.get(i.get("tipo"), ""))]
        cats = self.categorias()
        return cats[min(self.cat, len(cats) - 1)][2] if cats else []

    def abrir(self, lista, actual):
        self.lista, self.actual, self.filtro, self.abierto = list(lista), actual, "", True
        self.cat = self.idx = 0
        for ci, (_, _, items) in enumerate(self.categorias()):
            for ii, it in enumerate(items):
                if it.get("id") == actual:
                    self.cat, self.idx = ci, ii

    def cerrar(self):
        self.abierto = False

    def tecla(self, codigo):
        """Una pulsación (o repetición) con el menú abierto -> [] o [("router", "instrumento ya <id>")]."""
        items = self.visibles()
        if codigo in (KEY_ESC, KEY_F9):
            self.cerrar()
        elif codigo == KEY_ENTER:
            if items:
                elegido = items[min(self.idx, len(items) - 1)]
                self.cerrar()
                return [("router", f"instrumento ya {elegido['id']}")]
        elif codigo in (KEY_LEFT, KEY_RIGHT):
            cats = self.categorias()
            if cats and not self.filtro:
                self.cat, self.idx = (self.cat + (1 if codigo == KEY_RIGHT else -1)) % len(cats), 0
        elif codigo in (KEY_UP, KEY_DOWN):
            if items:
                self.idx = (min(self.idx, len(items) - 1) + (1 if codigo == KEY_DOWN else -1)) % len(items)
        elif codigo == KEY_BACKSPACE:
            self.filtro, self.idx = self.filtro[:-1], 0
        elif codigo in LETRAS and len(self.filtro) < self.MAX_FILTRO:
            self.filtro, self.idx = self.filtro + LETRAS[codigo], 0
        return []


class MenuSalidas:
    """Menú de salidas de audio (F10, fase 10): la lista que publica el enrutador (tarjetas USB y salidas de la Pi).
    Sin E/S: ENTER en otra salida devuelve la orden «salida <node.name>» para el enrutador."""

    def __init__(self):
        self.abierto = False
        self.lista = []                 # [{"nombre", "visible", "tipo", "aviso", "activa"}]
        self.idx = 0

    def abrir(self, lista):
        self.lista, self.abierto = list(lista), True
        self.idx = next((i for i, s in enumerate(self.lista) if s.get("activa")), 0)

    def cerrar(self):
        self.abierto = False

    def tecla(self, codigo):
        if codigo in (KEY_ESC, KEY_F10):
            self.cerrar()
        elif codigo in (KEY_UP, KEY_DOWN) and self.lista:
            self.idx = (self.idx + (1 if codigo == KEY_DOWN else -1)) % len(self.lista)
        elif codigo == KEY_ENTER and self.lista:
            elegida = self.lista[min(self.idx, len(self.lista) - 1)]
            self.cerrar()
            if not elegida.get("activa"):
                return [("router", f"salida {elegida['nombre']}")]
        return []


class ConfirmarApagado:
    """Ventana «¿Apagar la Raspberry Pi?» (F12, fase 11): S apaga; N, ESC o F12 otra vez, no. Las demás teclas no
    hacen nada (tampoco suenan): nadie apaga la Pi por accidente tocando."""

    def __init__(self):
        self.abierto = False

    def abrir(self):
        self.abierto = True

    def cerrar(self):
        self.abierto = False

    def tecla(self, codigo):
        if codigo == KEY_S:
            self.cerrar()
            return [("apagar",)]
        if codigo in (KEY_N, KEY_ESC, KEY_F12):
            self.cerrar()
        return []


LINEAS_APAGAR = ["¿Apagar la Raspberry Pi?", "", "S   sí, apagar", "N   no, seguir tocando", "",
                 "Desenchúfala cuando se apague la luz verde"]


class Interprete:
    """Traduce eventos de tecla en mensajes. Sin E/S: se prueba de forma aislada.

    MIDI: ("on", nota, vel) | ("off", nota) | ("cc", control, valor) | ("salir",) | ("apagar",)
    Otros (los atiende Controles): ("volumen", ±1) | ("reverb", ±1) | ("router", orden) | ("seleccion", ±1)
    | ("alternar_seleccion",)
    """

    def __init__(self, octava=4, fuerza=80, instrumentos=None, salidas=None):
        self.menu = MenuInstrumentos()
        self.menu_salida = MenuSalidas()
        self.confirmar = ConfirmarApagado()
        self.instrumentos = instrumentos   # función -> (lista, id actual) para abrir el menú (o None)
        self.salidas = salidas             # función -> lista de salidas para el menú F10 (o None)
        self.octava = max(OCTAVA_MIN, min(OCTAVA_MAX, octava))
        self.fuerza = min(FUERZAS, key=lambda f: abs(f - fuerza))
        self.pedal = False
        self.sonando = {}        # código de tecla -> nota que se envió al pulsarla
        self.ultima = None

    def nota_de(self, codigo):
        return 12 * (self.octava + 1) + NOTAS_POR_TECLA[codigo]

    def evento(self, codigo, valor):
        abierto = next((v for v in (self.confirmar, self.menu, self.menu_salida) if v.abierto), None)
        if abierto is not None:
            if valor == 0:
                # Al soltar una tecla que sonaba antes de abrir el menú, su nota (o el pedal) se suelta igual.
                nota = self.sonando.pop(codigo, None)
                if nota is not None:
                    return [("off", nota)]
                if codigo == KEY_SPACE and self.pedal:
                    self.pedal = False
                    return [("cc", 64, 0)]
                return []
            if valor != 1 and abierto is self.confirmar:
                return []                           # la repetición de una tecla no confirma ni cancela
            res = abierto.tecla(codigo)             # las letras buscan (F9) o no hacen nada (F10, F12): no suenan
            return self.apagar_todo() + res if res == [("apagar",)] else res
        if valor == 1 and codigo == KEY_F12:
            self.confirmar.abrir()
            return []
        if valor == 1 and codigo == KEY_F9:
            lista, actual = self.instrumentos() if self.instrumentos else ([], None)
            if lista:
                self.menu.abrir(lista, actual)
            return []
        if valor == 1 and codigo == KEY_F10:
            lista = self.salidas() if self.salidas else []
            if lista:
                self.menu_salida.abrir(lista)
            return []
        # Volumen y reverb admiten la repetición automática: mantener la flecha cambia el valor seguido.
        if valor in (1, 2) and codigo in (KEY_UP, KEY_DOWN):
            return [("volumen", 1 if codigo == KEY_UP else -1)]
        if valor in (1, 2) and codigo in (KEY_LEFT, KEY_RIGHT):
            return [("reverb", 1 if codigo == KEY_RIGHT else -1)]
        if valor == 2:                       # repetición automática: se ignora
            return []
        pulsada = valor == 1
        if codigo == KEY_BACKSPACE and pulsada:
            return self.panico() + [("router", "panico")]
        if pulsada and codigo in ORDENES_TECLA:
            return [("router", ORDENES_TECLA[codigo])]
        if pulsada and codigo == KEY_TAB:
            return [("seleccion", 1)]
        if pulsada and codigo == KEY_ENTER:
            return [("alternar_seleccion",)]
        if codigo == KEY_ESC and pulsada:
            return self.apagar_todo() + [("salir",)]
        if codigo == KEY_SPACE:
            self.pedal = pulsada
            return [("cc", 64, 127 if pulsada else 0)]
        if pulsada and codigo in (KEY_Z, KEY_X):
            self.octava = max(OCTAVA_MIN, min(OCTAVA_MAX, self.octava + (1 if codigo == KEY_X else -1)))
            return []
        if pulsada and codigo in (KEY_C, KEY_V):
            i = FUERZAS.index(self.fuerza) + (1 if codigo == KEY_V else -1)
            self.fuerza = FUERZAS[max(0, min(len(FUERZAS) - 1, i))]
            return []
        if codigo not in NOTAS_POR_TECLA:
            return []
        if pulsada:
            if codigo in self.sonando:       # ya sonando (no debería ocurrir sin auto-repetición)
                return []
            nota = self.nota_de(codigo)
            if not NOTA_MIN <= nota <= NOTA_MAX:
                return []
            self.sonando[codigo] = nota
            self.ultima = nota
            return [("on", nota, self.fuerza)]
        # Al soltar se apaga la nota que sonó al pulsar, aunque se haya cambiado de octava entretanto.
        nota = self.sonando.pop(codigo, None)
        return [] if nota is None else [("off", nota)]

    def apagar_todo(self):
        msgs = [("off", n) for n in self.sonando.values()]
        self.sonando.clear()
        if self.pedal:
            self.pedal = False
            msgs.append(("cc", 64, 0))
        return msgs

    def panico(self):
        """Silencio inmediato: apaga lo que suena, suelta el pedal y envía All Notes Off / All Sound Off."""
        msgs = self.apagar_todo()
        if ("cc", 64, 0) not in msgs:
            msgs.append(("cc", 64, 0))
        return msgs + [("cc", 123, 0), ("cc", 120, 0)]

    def estado(self):
        ult = nombre_nota(self.ultima) if self.ultima is not None else "-"
        return (f"Octava {self.octava} (A = {nombre_nota(12 * (self.octava + 1))}) | Fuerza {self.fuerza:3d} | "
                f"Pedal {'si' if self.pedal else 'no'} | Ultima {ult:5s} | Sonando {len(self.sonando)}")


# --- Secuenciador ALSA (módulo común alsa_seq.py) ----------------------------------------------
from alsa_seq import (EventoSeq, construir_evento, ClienteSeq, SEQ_OPEN_OUTPUT,  # noqa: E402,F401
                      SEQ_EVENT_NOTEON, SEQ_EVENT_NOTEOFF, SEQ_EVENT_CONTROLLER, SEQ_QUEUE_DIRECT,
                      SEQ_ADDRESS_SUBSCRIBERS, SEQ_ADDRESS_UNKNOWN)


class SalidaSeq:
    """Puerto MIDI de salida "<cliente>:notas" al que se suscriben el enrutador o PipeWire."""

    def __init__(self, nombre_cliente="Teclado Piano", nombre_puerto="notas"):
        self.c = ClienteSeq(nombre_cliente, SEQ_OPEN_OUTPUT)
        self.puerto = self.c.puerto_salida(nombre_puerto)
        self.cliente = self.c.cliente

    def enviar(self, msg):
        self.c.enviar(msg, self.puerto)

    def cerrar(self):
        self.c.cerrar()


# --- Controles que no son MIDI: volumen (G1), enrutador (sonido, entradas, reverb), sistema -------------
def _ejecutar(args):
    import subprocess
    return subprocess.run(args, capture_output=True, text=True, timeout=3)


def leer_estado_piano(ruta):
    """Lee el archivo clave=valor que publica piano-en-vivo.sh. Devuelve {} si no existe."""
    datos = {}
    try:
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                if "=" in linea:
                    k, v = linea.strip().split("=", 1)
                    datos[k] = v
    except OSError:
        pass
    return datos


def escribir_fifo(ruta, texto):
    """Escribe una línea en un FIFO sin bloquear. False si no hay lector o no existe."""
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        os.write(fd, (texto + "\n").encode())
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


class Controles:
    PASO_VOLUMEN = 0.05
    PASO_REVERB = 0.05
    VOLUMEN_MAX = 1.0           # 100 % = 0 dB en el control de la G1 (no se amplifica por encima)
    INTERVALO_VOLUMEN = 0.15    # s mínimos entre órdenes a la G1: al mantener la flecha se agrupan los pasos
                                # (cada orden es tráfico USB al mezclador de la G1, que puede provocar cortes)
    INTERVALO_SISTEMA = 2.0

    def __init__(self, ejecutar=_ejecutar, ctl_reverb=None, reverb=None, ctl_router=None, estado_router=None,
                 termica="/sys/class/thermal/thermal_zone0/temp", stat="/proc/stat", reloj=time.monotonic):
        self.ejecutar = ejecutar
        self.ctl_reverb = ctl_reverb
        self.reverb = reverb
        self.ctl_router, self.estado_router = ctl_router, estado_router
        self.router = None          # último estado leído del enrutador (dict) o None
        self.seleccion = 0          # índice de la entrada MIDI elegida en el panel
        self.termica, self.stat, self.reloj = termica, stat, reloj
        self.volumen = None
        self.silenciado = False
        self._volumen_pendiente = False
        self._t_volumen = None
        self._destino = None        # tarjeta a la que se leyó el volumen (al cambiar de salida se vuelve a leer)
        self.temp = self.cpu = None
        self.bajo_voltaje_ahora = self.limitado_ahora = self.bajo_voltaje_hubo = False
        self._cpu_prev = None
        self._t_sistema = None
        self.leer_router()
        self.leer_volumen()

    @classmethod
    def desde_estado(cls, ruta, **kw):
        e = leer_estado_piano(ruta)
        try:
            mix = float(e["reverb_mix"]) if "reverb_mix" in e else None
        except ValueError:
            mix = None
        return cls(ctl_reverb=e.get("reverb_ctl"), reverb=mix, ctl_router=e.get("router_ctl"),
                   estado_router=e.get("router_estado"), **kw)

    # Volumen de la tarjeta que usa el piano (la publica el enrutador, fase 10) mediante wpctl; sin enrutador, el de
    # la salida por defecto del sistema
    def destino_volumen(self):
        activa = ((self.router or {}).get("salida") or {}).get("activa") or {}
        return str(activa["id"]) if activa.get("id") is not None else "@DEFAULT_AUDIO_SINK@"

    def leer_volumen(self):
        self._destino = self.destino_volumen()
        try:
            r = self.ejecutar(["wpctl", "get-volume", self._destino])
            partes = r.stdout.split()
            self.volumen = float(partes[1])           # "Volume: 0.30 [MUTED]"
            self.silenciado = "[MUTED]" in r.stdout
        except Exception:  # noqa: BLE001  (wpctl ausente, salida inesperada...)
            self.volumen = None

    def cambiar_volumen(self, delta):
        """Un paso de volumen. Se ve al instante; la orden a la G1 sale ya si pasó INTERVALO_VOLUMEN desde la
        anterior y, si no, la envía aplicar_volumen() en la siguiente vuelta del bucle con el valor final."""
        if self.volumen is None:
            self.leer_volumen()
            if self.volumen is None:
                return
        self.volumen = round(min(self.VOLUMEN_MAX, max(0.0, self.volumen + delta * self.PASO_VOLUMEN)), 2)
        self._volumen_pendiente = True
        self.aplicar_volumen()

    def aplicar_volumen(self, forzar=False):
        """Envía a la G1 el volumen pendiente (como mucho una orden cada INTERVALO_VOLUMEN, salvo forzar).
        wpctl pide el cambio a WirePlumber y vuelve enseguida: una lectura inmediata puede devolver aún el valor
        anterior si el sistema está ocupado. Se muestra el valor pedido y actualizar_sistema() vuelve a leer el
        real cada pocos segundos (eso refleja también cambios hechos desde fuera)."""
        if not self._volumen_pendiente:
            return
        ahora = self.reloj()
        if not forzar and self._t_volumen is not None and ahora - self._t_volumen < self.INTERVALO_VOLUMEN:
            return
        try:
            r = self.ejecutar(["wpctl", "set-volume", self.destino_volumen(), f"{self.volumen:.2f}"])
            ok = getattr(r, "returncode", 0) == 0
        except Exception:  # noqa: BLE001
            ok = False
        self._t_volumen, self._volumen_pendiente = ahora, False
        if not ok:
            self.leer_volumen()

    def instrumentos(self):
        """(lista de instrumentos, id del actual) publicados por el enrutador, para el menú F9."""
        inst = (self.router or {}).get("instrumento") or {}
        return inst.get("lista") or [], (inst.get("actual") or {}).get("id")

    def salidas(self):
        """Salidas de audio publicadas por el enrutador, para el menú F10."""
        return ((self.router or {}).get("salida") or {}).get("lista") or []

    # Enrutador: estado (JSON) y órdenes (FIFO)
    def leer_router(self):
        if not self.estado_router:
            self.router = None
            return
        try:
            with open(self.estado_router, encoding="utf-8") as f:
                self.router = json.load(f)
        except (OSError, ValueError):
            self.router = None
            return
        if self.router.get("reverb") is not None:
            self.reverb = self.router["reverb"]
        n = len(self.router.get("fuentes", []))
        self.seleccion = min(self.seleccion, max(0, n - 1))
        # Otra tarjeta (o la misma reconectada con otro id): su volumen es otro (el enrutador aplica el recordado)
        if self._destino is not None and self.destino_volumen() != self._destino and not self._volumen_pendiente:
            self.leer_volumen()

    def orden_router(self, texto):
        return bool(self.ctl_router) and escribir_fifo(self.ctl_router, texto)

    def fuentes(self):
        return (self.router or {}).get("fuentes", [])

    def cambiar_reverb(self, delta):
        if self.router is not None and self.orden_router(f"reverb {'+1' if delta > 0 else '-1'}"):
            if self.reverb is not None:      # se ve al instante; el enrutador confirma en su estado
                self.reverb = round(min(1.0, max(0.0, self.reverb + delta * self.PASO_REVERB)), 2)
            return
        # Sin enrutador: directamente a jalv por su FIFO ("mix = 0.40")
        if not self.ctl_reverb or self.reverb is None:
            return
        nuevo = round(min(1.0, max(0.0, self.reverb + delta * self.PASO_REVERB)), 2)
        if escribir_fifo(self.ctl_reverb, f"mix = {nuevo:.2f}"):
            self.reverb = nuevo
        else:
            self.ctl_reverb = None                   # sin lector: se desactiva el control

    def aplicar(self, msg):
        tipo = msg[0]
        if tipo == "volumen":
            self.cambiar_volumen(msg[1])
        elif tipo == "reverb":
            self.cambiar_reverb(msg[1])
        elif tipo == "router":
            self.orden_router(msg[1])
        elif tipo == "seleccion":
            n = len(self.fuentes())
            if n:
                self.seleccion = (self.seleccion + msg[1]) % n
        elif tipo == "alternar_seleccion":
            f = self.fuentes()
            if f:
                self.orden_router(f"fuente alternar {f[min(self.seleccion, len(f) - 1)]['id']}")

    # Estado del sistema (cada INTERVALO_SISTEMA segundos)
    def actualizar_sistema(self):
        self.aplicar_volumen()
        self.leer_router()
        ahora = self.reloj()
        if self._t_sistema is not None and ahora - self._t_sistema < self.INTERVALO_SISTEMA:
            return
        self._t_sistema = ahora
        if not self._volumen_pendiente:      # no pisar con la lectura un cambio que aún no se envió
            self.leer_volumen()
        try:
            with open(self.termica) as f:
                self.temp = int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            self.temp = None
        try:
            with open(self.stat) as f:
                campos = [int(x) for x in f.readline().split()[1:]]
            total, ocioso = sum(campos), campos[3] + (campos[4] if len(campos) > 4 else 0)
            if self._cpu_prev:
                dt, di = total - self._cpu_prev[0], ocioso - self._cpu_prev[1]
                self.cpu = round(100.0 * (dt - di) / dt) if dt > 0 else None
            self._cpu_prev = (total, ocioso)
        except (OSError, ValueError, IndexError):
            self.cpu = None
        try:
            r = self.ejecutar(["vcgencmd", "get_throttled"])
            bits = int(r.stdout.strip().split("=")[1], 16)
            self.bajo_voltaje_ahora = bool(bits & 0x1)
            self.limitado_ahora = bool(bits & 0x4)
            self.bajo_voltaje_hubo = bool(bits & 0x10000)
        except Exception:  # noqa: BLE001
            pass


# --- Paneles (funciones puras; solo caracteres de la fuente de la consola, ver glifos_consola.txt) ------
def barra(valor, ancho=12):
    """Barra de texto para un valor 0..1; '?' si no se conoce."""
    if valor is None:
        return "?" * ancho
    llenos = round(max(0.0, min(1.0, valor)) * ancho)
    return "█" * llenos + "░" * (ancho - llenos)


def lineas_controles():
    """Panel de ayuda: (tecla, acción)."""
    return [
        ("Notas", "A S D F G H J K L Ñ {"),
        ("Sost.", "W E   T Y U   O P"),
        ("Octava", "Z baja      X sube"),
        ("Fuerza", "C menos     V más"),
        ("Pedal", "ESPACIO (mantener)"),
        ("Sonido", "F6 anterior F7 siguiente"),
        ("Menú", "F9 sonidos por categoría"),
        ("Salida", "F10 tarjeta de sonido"),
        ("Volumen", "Flecha arriba / abajo"),
        ("Reverb", "Flecha der. / izq."),
        ("Transp.", "F1 baja     F2 sube"),
        ("Curva", "F3 suave/normal/dura"),
        ("Latencia", "F4 128/256/512/1024"),
        ("Entrada", "TAB elegir  ENTER on/off"),
        ("Nuevas", "F5 conectar solas sí/no"),
        ("Silencio", "RETROCESO"),
        ("Salir", "ESC        F12 apagar la Pi"),
    ]


def lineas_estado(interp, controles=None):
    """Panel ESTADO: (etiqueta, texto, aviso). aviso=True se resalta."""
    i = FUERZAS.index(interp.fuerza)
    filas = [
        ("Octava", f"{interp.octava}   (tecla A = {nombre_nota(12 * (interp.octava + 1))})", False),
        ("Fuerza", f"{'█' * (i + 1)}{'░' * (len(FUERZAS) - i - 1)}  {interp.fuerza:3d}", False),
    ]
    r = controles.router if controles is not None else None
    pedal = r.get("pedal", interp.pedal) if r else interp.pedal
    filas.append(("Pedal", "PISADO" if pedal else "suelto", pedal))
    if r and r.get("ultima"):
        n, v, fuente = r["ultima"]
        filas.append(("Ultima", f"{nombre_nota(n)} f{v} {fuente}"[:28], False))
    else:
        ult = nombre_nota(interp.ultima) if interp.ultima is not None else "-"
        filas.append(("Ultima", f"{ult}", False))
    if controles is not None:
        vol = controles.volumen
        filas.append(("Volumen", f"{barra(vol)} {'---' if vol is None else f'{round(vol * 100):3d}%'}"
                                 f"{' MUDO' if controles.silenciado else ''}", controles.silenciado))
        rev = controles.reverb if (controles.ctl_reverb or r) else None
        filas.append(("Reverb", f"{barra(rev)} {'---' if rev is None else f'{round(rev * 100):3d}%'}", False))
        partes = []
        if controles.temp is not None:
            partes.append(f"{controles.temp:.0f}°C")
        if controles.cpu is not None:
            partes.append(f"CPU {controles.cpu}%")
        aviso = controles.bajo_voltaje_ahora or controles.limitado_ahora
        if controles.bajo_voltaje_ahora:
            partes.append("BAJO VOLTAJE!")
        elif controles.limitado_ahora:
            partes.append("CPU LIMITADA!")
        elif controles.bajo_voltaje_hubo:
            partes.append("(hubo bajo volt.)")
        filas.append(("Sistema", "  ".join(partes) or "-", aviso))
    return filas


def lineas_instrumento(inst):
    """Filas del instrumento en el panel SONIDO: el que suena y, debajo, su estado (cargando, error...)."""
    if not inst:
        return []
    def nombre(clave):
        return (inst.get(clave) or {}).get("nombre", "")
    actual = nombre("actual")
    filas = [("Sonido", (actual or "(ninguno)")[:ANCHO_VALOR], not actual)]
    estado = inst.get("estado")
    if estado == "cargando":
        texto, aviso = f"cargando: {nombre('cargando')}", False
    elif estado == "elegido":
        texto, aviso = f"> {nombre('elegido')}", False
    elif estado == "error":
        texto, aviso = f"ERROR: {inst.get('error') or '?'}", True
    else:
        texto, aviso = f"{inst.get('posicion') or '-'} de {inst.get('total') or '-'}   F6/F7 cambiar", False
    return filas + [("", t, aviso) for t in partir(texto, ANCHO_VALOR)]


def partir(texto, ancho, lineas=2):
    """Parte un texto en palabras en hasta `lineas` filas de `ancho` (la última se recorta si no cabe)."""
    if len(texto) <= ancho:
        return [texto]
    filas, actual = [], ""
    for palabra in texto.split():
        if actual and len(actual) + 1 + len(palabra) > ancho:
            filas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}" if actual else palabra
    filas.append(actual)
    if len(filas) > lineas:
        filas = filas[:lineas - 1] + [" ".join(filas[lineas - 1:])]
    return [f[:ancho] for f in filas]


def partir_entero(texto, ancho, lineas=2, url=False):
    """Parte un texto en hasta `lineas` filas de `ancho` SIN recortarlo nunca: por palabras o, si es una dirección
    web, tras cada «/». None si no cabe entero (la interfaz no muestra datos a medias)."""
    trozos = re.findall(r"[^/]*/|[^/]+", texto) if url else texto.split()
    union = "" if url else " "
    filas, actual = [], ""
    for t in trozos:
        if len(t) > ancho:
            return None
        if actual and len(actual) + len(union) + len(t) > ancho:
            filas.append(actual)
            actual = t
        else:
            actual = f"{actual}{union}{t}" if actual else t
    if actual:
        filas.append(actual)
    return filas if 0 < len(filas) <= lineas else None


# Créditos de un sonido (datos del catálogo que publica el enrutador en su lista), en el orden en que se muestran.
DETALLE_SONIDO = (("autor", "Autor"), ("licencia", "Licencia"), ("uso", "Uso"), ("fuente", "Fuente"))
PRIORIDAD_CREDITOS = ("uso", "licencia", "autor", "fuente")     # si no caben todos, se quitan desde el final


def detalle_sonido(it):
    """[(clave, etiqueta, texto, resaltar)] con los créditos que tenga un sonido de la lista del enrutador.
    resaltar: el uso de un sonido con restricción (no comercial, no redistribuir...)."""
    it = it or {}
    return [(clave, etiqueta, it[clave].strip(), clave == "uso" and it.get("restringido") is True)
            for clave, etiqueta in DETALLE_SONIDO if isinstance(it.get(clave), str) and it[clave].strip()]


def lineas_creditos(it, max_filas, ancho=None):
    """Panel SOBRE ESTE SONIDO de la pantalla principal: [(etiqueta, texto, resaltar)], como mucho max_filas.
    Solo datos ENTEROS: cada uno ocupa de una a tres filas (la dirección web, sin «http(s)://», partida tras «/»); el que
    no cabe así no se muestra, y si no caben todos se quitan por PRIORIDAD_CREDITOS (la fuente primero, el uso
    el último). El detalle completo está en el menú F9."""
    ancho = ancho or ANCHO_VALOR
    bloques = []
    for clave, etiqueta, texto, resaltar in detalle_sonido(it):
        if clave == "fuente":
            texto = re.sub(r"^https?://", "", texto)
        trozos = partir_entero(texto, ancho, 3, url=clave == "fuente")
        if trozos:
            bloques.append((clave, etiqueta, trozos, resaltar))
    while bloques and sum(len(b[2]) for b in bloques) > max_filas:
        bloques.remove(max(bloques, key=lambda b: PRIORIDAD_CREDITOS.index(b[0])))
    return [(etiqueta if k == 0 else "", t, resaltar)
            for _, etiqueta, trozos, resaltar in bloques for k, t in enumerate(trozos)]


def sonido_actual(controles):
    """El sonido que suena, tal como lo publica el enrutador en su lista (con sus créditos), o None."""
    inst = ((controles.router or {}).get("instrumento") or {}) if controles is not None else {}
    iid = (inst.get("actual") or {}).get("id")
    return next((i for i in inst.get("lista") or [] if i.get("id") == iid), None) if iid else None


def progreso_carga(transcurrido, estimado):
    """Progreso estimado (0..0,99) de una carga: lineal hasta el 90 % del tiempo previsto y después se acerca al
    99 % sin llegar. sfizz no informa su avance; el 100 % es la confirmación real (la ventana se cierra)."""
    r = max(0.0, transcurrido) / (estimado if estimado and estimado > 0 else 1.0)
    if r <= 0.9:
        return r
    return 0.9 + 0.09 * (1 - math.exp(-(r - 0.9) * 3))


ANCHO_BARRA_CARGA = 34


def lineas_modal(controles, ahora=None, menu_abierto=False):
    """Contenido de la ventana centrada (o None): «Cargando instrumento» (título, nombre, barra y aviso) o, de la
    salida de audio (fase 10), «Cambiando la salida» y «Salida desconectada» (esta, no con un menú abierto: así se
    puede elegir otra con F10)."""
    r = controles.router if controles is not None else None
    carga = (((r or {}).get("instrumento") or {}).get("carga")) if r else None
    salida = (r or {}).get("salida") or {}
    if not carga and salida.get("estado") == "cambiando":
        return ["Cambiando la salida de audio", "", salida.get("destino") or "?", "",
                "El piano está en pausa un momento"]
    if not carga and salida.get("estado") == "desconectada" and not menu_abierto:
        return ["Salida de audio desconectada", "", (salida.get("activa") or {}).get("visible") or "?", "",
                "Vuelve a conectarla o elige otra con F10"]
    if not carga:
        return None
    ahora = time.time() if ahora is None else ahora
    p = progreso_carga(ahora - float(carga.get("inicio") or ahora), carga.get("estimado_s"))
    llenos = round(p * ANCHO_BARRA_CARGA)
    lineas = ["Cargando instrumento", "", carga.get("nombre", "?"),
              "█" * llenos + "░" * (ANCHO_BARRA_CARGA - llenos) + f" {round(p * 100):3d} %", "",
              "El piano está en pausa hasta que termine"]
    if carga.get("despues"):
        lineas.append(f"Después: {carga['despues'].get('nombre', '?')}")
    return lineas


MENU_FILAS = 7      # instrumentos visibles a la vez en el menú (con desplazamiento si hay más)
MENU_DETALLE = len(DETALLE_SONIDO)    # filas de créditos del sonido marcado (completos, una fila cada uno)
# Créditos del proyecto, al pie del menú F9 (fase 09; ver CREDITOS.md)
CREDITO_PROYECTO = "Piano Raspberry Pi · creado por Reinaldo Johnson Espinoza, con la ayuda de Claude (Anthropic)"


def lineas_menu(menu, ancho=None):
    """Filas del menú F9: [(texto, estilo)] con estilo "titulo" | "pestanas" | "linea" | "item" | "sel" | "detalle"
    | "restringido" | "ayuda" | "credito". Debajo de la lista, los créditos COMPLETOS del sonido marcado (autor,
    licencia, uso y fuente; el catálogo limita su largo para que quepan enteros); al pie, los créditos del proyecto."""
    ancho = ancho or ANCHO_PANELES
    filas = [(" SONIDOS por categoría", "titulo")]
    if menu.filtro:
        filas.append((f" Buscar: {menu.filtro}_", "pestanas"))
    else:
        pestanas = []
        for ci, (_, nombre, _) in enumerate(menu.categorias()):
            pestanas.append(f"[{nombre}]" if ci == menu.cat else f" {nombre} ")
        filas.append((" " + " ".join(pestanas), "pestanas"))
    filas.append(("─" * ancho, "linea"))
    items = menu.visibles()
    idx = min(menu.idx, max(0, len(items) - 1))
    desde = max(0, min(idx - MENU_FILAS // 2, len(items) - MENU_FILAS))
    for k in range(desde, min(len(items), desde + MENU_FILAS)):
        it = items[k]
        texto = f" {'>' if k == idx else ' '} {it['nombre']:<30}"
        if menu.filtro:
            texto += f" {cat.NOMBRE_CATEGORIA.get(it.get('tipo'), '')}"
        if it.get("id") == menu.actual:
            texto += "   (suena ahora)"
        filas.append((texto, "sel" if k == idx else "item"))
    if not items:
        filas.append(("   (ningún instrumento coincide)", "item"))
    for _ in range(MENU_FILAS - max(1, min(len(items), MENU_FILAS))):
        filas.append(("", "item"))
    filas.append(("─" * ancho, "linea"))
    detalle = detalle_sonido(items[idx]) if items else []
    for _, etiqueta, texto, resaltar in detalle:
        filas.append((f" {etiqueta:<9} {texto}", "restringido" if resaltar else "detalle"))
    for _ in range(MENU_DETALLE - len(detalle)):
        filas.append(("", "detalle"))
    filas.append(("─" * ancho, "linea"))
    filas.append((" ←/→ categoría    ↑/↓ elegir    ENTER cargar    letras: buscar (RETROCESO borra)"
                  "    F9 o ESC: cerrar", "ayuda"))
    filas.append((f" {CREDITO_PROYECTO}", "credito"))
    return [(t[:ancho], e) for t, e in filas]


MENU_SALIDAS_FILAS = 6      # salidas visibles a la vez en el menú F10 (fase 10)
TIPO_SALIDA = {"usb": "USB", "pi": "Pi", "hdmi": "HDMI", "otra": ""}


def lineas_menu_salidas(menu, ancho=None):
    """Filas del menú F10: [(texto, estilo)] con los mismos estilos que el F9. Cada salida con su tipo, «(suena
    ahora)» en la activa y su aviso (calidad de la Pi, HDMI, necesita 48 kHz) debajo de la lista para la marcada."""
    ancho = ancho or ANCHO_PANELES
    filas = [(" SALIDA DE AUDIO (tarjeta de sonido)", "titulo"), ("─" * ancho, "linea")]
    idx = min(menu.idx, max(0, len(menu.lista) - 1))
    desde = max(0, min(idx - MENU_SALIDAS_FILAS // 2, len(menu.lista) - MENU_SALIDAS_FILAS))
    for k in range(desde, min(len(menu.lista), desde + MENU_SALIDAS_FILAS)):
        s = menu.lista[k]
        texto = f" {'>' if k == idx else ' '} {s.get('visible', '?'):<34} {TIPO_SALIDA.get(s.get('tipo'), ''):<5}"
        if s.get("activa"):
            texto += " (suena ahora)"
        filas.append((texto, "sel" if k == idx else "item"))
    if not menu.lista:
        filas.append(("   (ninguna salida de audio)", "item"))
    for _ in range(MENU_SALIDAS_FILAS - max(1, min(len(menu.lista), MENU_SALIDAS_FILAS))):
        filas.append(("", "item"))
    filas.append(("─" * ancho, "linea"))
    marcada = menu.lista[idx] if menu.lista else {}
    aviso = marcada.get("aviso")
    filas.append(((f" Aviso: {aviso}" if aviso else ""), "restringido" if aviso else "detalle"))
    filas.append((" ↑/↓ elegir    ENTER usar esta salida    F10 o ESC: cerrar", "ayuda"))
    return [(t[:ancho], e) for t, e in filas]


def titulo_ventana(base, controles):
    """Título de la interfaz: el instrumento que suena, si el enrutador lo publica."""
    inst = ((controles.router or {}).get("instrumento") or {}) if controles is not None else {}
    actual = (inst.get("actual") or {}).get("nombre")
    return f"{actual} - Raspberry Pi" if actual else base


def lineas_sonido(controles):
    """Panel SONIDO: (etiqueta, texto, aviso)."""
    r = controles.router if controles is not None else None
    if not r:
        return [("Enrutador", "no disponible", True)]
    t = r.get("transposicion", 0)
    q = r.get("latencia")
    tasa = (r.get("salida") or {}).get("tasa") or RATE
    filas = lineas_instrumento(r.get("instrumento")) + lineas_salida(r.get("salida")) + [
        ("Transp.", f"{t:+d} semitonos" if t else "0 (sin transponer)", t != 0),
        ("Curva", r.get("curva", "?"), False),
        ("Latencia", f"{q} ({1000 * q / tasa:.1f} ms)".replace(".", ",") if q else "?", False),
    ]
    x, hace = r.get("xruns"), r.get("xrun_hace")
    if x is None:
        filas.append(("Cortes", "?", False))
    elif x == 0:
        filas.append(("Cortes", "0", False))
    else:
        reciente = hace is not None and hace < 10
        filas.append(("Cortes", f"{x} (último hace {hace:.0f} s)" if hace is not None else f"{x}", reciente))
    return filas


def lineas_salida(salida):
    """Filas «Salida» del panel SONIDO (fase 10): la tarjeta en uso y, debajo, su aviso o el error de la última orden
    (alternativa usada, desconectada, necesita 48 kHz...), en rojo. Sin salida publicada (modo silencio): nada."""
    if not salida:
        return []
    activa = (salida.get("activa") or {}).get("visible") or "?"
    if salida.get("estado") == "desconectada":
        return [("Salida", f"{activa} (desconectada)"[:ANCHO_VALOR], True)]
    aviso = salida.get("error") or salida.get("aviso")
    filas = [("Salida", activa[:ANCHO_VALOR], bool(aviso))]
    return filas + [("", t, True) for t in partir(aviso, ANCHO_VALOR)] if aviso else filas


def lineas_entradas(controles, ancho=38):
    """Panel ENTRADAS MIDI: (texto, seleccionada, activa, conectada)."""
    filas = []
    fuentes = controles.fuentes() if controles is not None else []
    for i, f in enumerate(fuentes):
        marca = ">" if i == controles.seleccion else " "
        casilla = "[x]" if f["activa"] else "[ ]"
        tipo = "PC" if f["tipo"] == "pc" else "MIDI"
        estado = "" if f["conectada"] else " desconect."
        nombre_max = ancho - len(f"{marca} {casilla}  ({tipo}){estado}")
        filas.append((f"{marca} {casilla} {f['nombre'][:nombre_max]} ({tipo}){estado}", i == controles.seleccion,
                      f["activa"], f["conectada"]))
    if not fuentes:
        filas.append(("  (sin entradas detectadas)", False, False, False))
    return filas


# --- Teclado dibujado de varias octavas (geometría pura) -----------------------------------------------
N_OCTAVAS = 4
SEMITONOS_BLANCOS = (0, 2, 4, 5, 7, 9, 11)


def inicio_teclado(octava, transposicion=0, n_octavas=N_OCTAVAS):
    """Do inicial de la vista: una octava por debajo de la zona del teclado de computador, sin salir de
    Do0 (12)..Do8 (108)."""
    pc = 12 * (octava + 1) + transposicion
    o = max(1, min(9 - n_octavas, pc // 12 - 1))
    return 12 * o


def etiquetas_pc(octava, transposicion=0):
    """{nota que suena: letra del teclado de computador}."""
    base = 12 * (octava + 1) + transposicion
    return {base + s: ETIQUETA[codigo] for codigo, s in NOTAS_POR_TECLA.items()}


def teclas_vista(inicio, n_octavas, ancho_blanca, sonando=(), etiquetas=None):
    """Lista de teclas a dibujar (blancas primero, luego negras encima):
    {nota, negra, x, ancho, alto, nombre, etiqueta, sonando, fuera}. x relativa al borde izquierdo."""
    etiquetas = etiquetas or {}
    sonando = set(sonando)
    alto_blanca = 8
    ancho_negra = 3 if ancho_blanca <= 5 else 4
    blancas, negras = [], []
    i = 0
    for nota in range(inicio, inicio + 12 * n_octavas + 1):
        s = nota % 12
        comun = {"nota": nota, "etiqueta": etiquetas.get(nota, ""), "sonando": nota in sonando,
                 "fuera": not NOTA_MIN <= nota <= NOTA_MAX}
        if s in SEMITONOS_BLANCOS:
            interior = ancho_blanca - 1
            nombre = nombre_nota(nota) if interior >= 4 else (NOMBRES_CORTOS[s] + str(nota // 12 - 1))[:interior]
            blancas.append(dict(comun, negra=False, x=i * ancho_blanca, ancho=ancho_blanca, alto=alto_blanca,
                                nombre=nombre))
            i += 1
        else:
            frontera = i * ancho_blanca
            negras.append(dict(comun, negra=True, x=frontera - ancho_negra // 2, ancho=ancho_negra, alto=5,
                               nombre=""))
    return blancas + negras


def ancho_teclas(ancho_pantalla, n_octavas=N_OCTAVAS):
    """Ancho de tecla blanca que cabe (4..8); 0 si no cabe."""
    w = (ancho_pantalla - 2) // (7 * n_octavas + 1)
    return min(8, w) if w >= 4 else 0


def mapa_88(inicio, fin, sonando_notas):
    """Línea de 88 caracteres (La0..Do8): '█' sonando, '═' zona dibujada, '·' resto."""
    return "".join("█" if n in sonando_notas else ("═" if inicio <= n <= fin else "·")
                   for n in range(NOTA_MIN, NOTA_MAX + 1))


ANCHO_COLUMNA, SEPARACION = 38, 2
ANCHO_VALOR = ANCHO_COLUMNA - 9          # texto a la derecha de la etiqueta en los paneles
ANCHO_PANELES = 3 * ANCHO_COLUMNA + 2 * SEPARACION                 # 118
ANCHO_MINIMO = max(ANCHO_PANELES, (7 * N_OCTAVAS + 1) * 4 + 2)     # 118
ALTO_MINIMO = 2 + 8 + 4 + 2 + len(lineas_controles())              # 30


# --- Entrada de teclado ------------------------------------------------------------------------
TECLAS_DE_LETRAS = (30, 44, 57)          # A, Z, ESPACIO: una interfaz de teclado "de verdad" las tiene


def tiene_letras(capacidades, bits_palabra=64):
    """¿El mapa de bits `capabilities/key` de sysfs (palabras hex, la más significativa primero) incluye las
    teclas de letras? Descarta las interfaces de teclas multimedia o de sistema del mismo teclado."""
    palabras = [int(w, 16) for w in reversed(capacidades.split())]
    def activa(n):
        i = n // bits_palabra
        return i < len(palabras) and bool(palabras[i] >> (n % bits_palabra) & 1)
    return all(activa(n) for n in TECLAS_DE_LETRAS)


def dispositivos_del_teclado(ruta, sysfs="/sys", dev="/dev/input", bits_palabra=None):
    """El evdev elegido y los demás del MISMO teclado USB con teclas de letras. Muchos teclados mecánicos
    envían las 6 primeras teclas simultáneas por la interfaz principal ("boot") y el resto por otra interfaz:
    sin leerla y capturarla, esas notas no suenan y lo tecleado llega a la consola."""
    bits_palabra = bits_palabra or (64 if sys.maxsize > 2 ** 32 else 32)
    elegido = os.path.basename(os.path.realpath(ruta))
    origen = os.path.realpath(os.path.join(sysfs, "class", "input", elegido, "device"))
    import re
    usb = origen                            # sube hasta el dispositivo USB (".../usb1/1-1/1-1.4"); sus
    while usb != os.path.dirname(usb) and not re.fullmatch(r"\d+-[\d.]+", os.path.basename(usb)):
        usb = os.path.dirname(usb)          # interfaces llevan ":" ("1-1.4:1.0") y no cuentan
    if usb == os.path.dirname(usb):         # no es USB: solo el elegido
        return [os.path.join(dev, elegido)]
    encontrados = [os.path.join(dev, elegido)]
    clase = os.path.join(sysfs, "class", "input")
    for nombre in sorted(os.listdir(clase), key=lambda n: (len(n), n)):
        if not nombre.startswith("event") or nombre == elegido:
            continue
        disp = os.path.realpath(os.path.join(clase, nombre, "device"))
        if not disp.startswith(usb + os.sep):
            continue
        try:
            with open(os.path.join(disp, "capabilities", "key")) as f:
                if tiene_letras(f.read(), bits_palabra):
                    encontrados.append(os.path.join(dev, nombre))
        except OSError:
            pass
    return encontrados


def buscar_teclado():
    candidatos = sorted(glob.glob("/dev/input/by-id/*-event-kbd"))
    preferidos = [c for c in candidatos if "keyboard" in c.lower()]
    return (preferidos or candidatos or [None])[0]


class LectorEvdev:
    """Convierte bytes leídos de un dispositivo evdev en (código, valor) de eventos EV_KEY.
    Acepta lecturas parciales: guarda los bytes sobrantes hasta completar un evento."""

    def __init__(self):
        self.pendiente = b""

    def alimentar(self, datos):
        self.pendiente += datos
        salida = []
        while len(self.pendiente) >= TAM_EVDEV:
            _, _, tipo, codigo, valor = struct.unpack(FORMATO_EVDEV, self.pendiente[:TAM_EVDEV])
            self.pendiente = self.pendiente[TAM_EVDEV:]
            if tipo == EV_KEY:
                salida.append((codigo, valor))
        return salida


def empaquetar_evento(codigo, valor, tipo=EV_KEY):
    """Inverso de LectorEvdev (para generar entradas de prueba)."""
    return struct.pack(FORMATO_EVDEV, 0, 0, tipo, codigo, valor)


AYUDA = ("Teclas: A W S E D F T G Y H U J K O L P Ñ { = do do# re re# mi fa fa# sol sol# la la# si do ...\n"
         "        Z/X octava   C/V fuerza   ESPACIO pedal   flechas arriba/abajo volumen\n"
         "        flechas der/izq reverb   F1/F2 transposición   F3 curva   F4 latencia   F5 nuevas\n"
         "        F6/F7 instrumento anterior/siguiente   F9 menú de sonidos por categorías\n"
         "        F10 salida de audio   TAB/ENTER entradas MIDI   RETROCESO silencio   ESC salir   F12 apagar")


# --- Interfaz de texto a pantalla completa (curses; funciona en la consola sin X y por SSH) ----------
class VistaTexto:
    def __init__(self, pantalla, titulo):
        import curses
        self.c = curses
        self.p = pantalla
        self.titulo = titulo
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)    # tecla blanca
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)    # tecla negra
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)    # tecla sonando
        curses.init_pair(4, curses.COLOR_YELLOW, -1)                   # títulos y etiquetas
        curses.init_pair(5, curses.COLOR_CYAN, -1)                     # información
        curses.init_pair(6, curses.COLOR_GREEN, -1)                    # notas sonando en el mapa
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_RED)      # avisos
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_CYAN)     # selección
        curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_BLUE)     # ventana de carga
        curses.init_pair(10, curses.COLOR_WHITE, -1)                   # créditos (con A_DIM: gris tenue)
        curses.init_pair(11, curses.COLOR_YELLOW, curses.COLOR_BLUE)   # restricción en el menú F9

    def cabe(self):
        alto, ancho = self.p.getmaxyx()
        return alto >= ALTO_MINIMO and ancho >= ANCHO_MINIMO

    def _escribir(self, y, x, texto, attr=0):
        alto, ancho = self.p.getmaxyx()
        if 0 <= y < alto and x < ancho:
            try:
                self.p.addstr(y, max(0, x), texto[: max(0, ancho - x - 1)], attr)
            except self.c.error:
                pass

    def _teclado(self, y, interp, controles):
        c = self.c
        alto, ancho = self.p.getmaxyx()
        r = controles.router if controles is not None else None
        transp = r.get("transposicion", 0) if r else 0
        sonando = set(r.get("sonando", [])) if r else set(interp.sonando.values())
        inicio = inicio_teclado(interp.octava, transp)
        w = ancho_teclas(ancho)
        total = (7 * N_OCTAVAS + 1) * w
        x0 = (ancho - total) // 2
        for t in teclas_vista(inicio, N_OCTAVAS, w, sonando, etiquetas_pc(interp.octava, transp)):
            if t["sonando"]:
                attr = c.color_pair(3) | c.A_BOLD
            elif t["negra"]:
                attr = c.color_pair(2)
            else:
                attr = c.color_pair(1)
            if t["fuera"]:
                attr |= c.A_DIM
            if t["negra"]:
                for fila in range(t["alto"]):
                    self._escribir(y + fila, x0 + t["x"], " " * t["ancho"], attr)
                if t["etiqueta"]:
                    self._escribir(y + t["alto"] - 1, x0 + t["x"] + (t["ancho"] - 1) // 2, t["etiqueta"],
                                   attr | c.A_BOLD)
            else:
                for fila in range(t["alto"]):
                    self._escribir(y + fila, x0 + t["x"], "│" + " " * (t["ancho"] - 1), attr)
                self._escribir(y + t["alto"] - 2, x0 + t["x"] + 1, t["nombre"].center(t["ancho"] - 1), attr)
                if t["etiqueta"]:
                    self._escribir(y + t["alto"] - 1, x0 + t["x"] + 1, t["etiqueta"].center(t["ancho"] - 1),
                                   attr | c.A_BOLD | c.A_UNDERLINE)
        for fila in range(8):
            self._escribir(y + fila, x0 + total, "│", c.color_pair(1))
        fin = inicio + 12 * N_OCTAVAS
        mapa = mapa_88(inicio, fin, sonando)
        xm = (ancho - len(mapa)) // 2
        self._escribir(y + 9, xm, "La0" + " " * (len(mapa) - 6) + "Do8", c.color_pair(5))
        for i, ch in enumerate(mapa):
            self._escribir(y + 10, xm + i, ch, c.color_pair(6) | c.A_BOLD if ch == "█" else c.color_pair(5))
        return y + 12

    def _panel(self, y, x, titulo, filas):
        """filas: (etiqueta, texto, aviso)."""
        c = self.c
        self._escribir(y, x, titulo, c.color_pair(4) | c.A_BOLD)
        self._escribir(y + 1, x, "─" * ANCHO_COLUMNA, c.color_pair(4))
        for n, (etiqueta, texto, aviso) in enumerate(filas):
            self._escribir(y + 2 + n, x, f"{etiqueta:9s}", c.color_pair(4))
            self._escribir(y + 2 + n, x + 9, texto[:ANCHO_COLUMNA - 9],
                           (c.color_pair(7) | c.A_BOLD) if aviso else c.color_pair(5))
        return y + 2 + len(filas)

    def _creditos(self, y, x, info):
        """Panel SOBRE ESTE SONIDO (abajo a la izquierda) en gris tenue, como letra chica: solo los datos que caben
        enteros hasta el borde inferior; la restricción, si la hay, resaltada."""
        alto, _ = self.p.getmaxyx()
        filas = lineas_creditos(info, alto - y - 2) if info else []
        if not filas:
            return
        c = self.c
        tenue = c.color_pair(10) | c.A_DIM
        self._escribir(y, x, "SOBRE ESTE SONIDO", c.color_pair(4) | c.A_DIM)
        self._escribir(y + 1, x, "─" * ANCHO_COLUMNA, c.color_pair(4) | c.A_DIM)
        for n, (etiqueta, texto, resaltar) in enumerate(filas):
            self._escribir(y + 2 + n, x, f"{etiqueta:9s}", tenue)
            self._escribir(y + 2 + n, x + 9, texto, (c.color_pair(4) | c.A_BOLD) if resaltar else tenue)

    def _menu(self, filas):
        """Menú F9 desplegado arriba, sobre el teclado dibujado."""
        c = self.c
        _, ancho = self.p.getmaxyx()
        x0 = max(0, (ancho - ANCHO_PANELES) // 2)
        estilos = {"titulo": c.color_pair(9) | c.A_BOLD, "pestanas": c.color_pair(9) | c.A_BOLD,
                   "linea": c.color_pair(9), "item": c.color_pair(9), "sel": c.color_pair(8) | c.A_BOLD,
                   "detalle": c.color_pair(9), "restringido": c.color_pair(11) | c.A_BOLD, "ayuda": c.color_pair(9),
                   "credito": c.color_pair(9) | c.A_DIM}
        for n, (texto, estilo) in enumerate(filas):
            self._escribir(1 + n, x0, texto.ljust(ANCHO_PANELES), estilos.get(estilo, c.color_pair(9)))

    def _modal(self, lineas):
        """Ventana centrada sobre el teclado dibujado (caracteres CP437)."""
        c = self.c
        alto, ancho = self.p.getmaxyx()
        interior = max(len(l) for l in lineas) + 6
        y0 = max(1, 2 + (11 - (len(lineas) + 2)) // 2)
        x0 = max(0, (ancho - interior - 2) // 2)
        attr = c.color_pair(9) | c.A_BOLD
        self._escribir(y0, x0, "┌" + "─" * interior + "┐", attr)
        for n, texto in enumerate(lineas):
            self._escribir(y0 + 1 + n, x0, "│" + texto.center(interior) + "│",
                           attr if n else c.color_pair(9) | c.A_BOLD | c.A_UNDERLINE)
        self._escribir(y0 + 1 + len(lineas), x0, "└" + "─" * interior + "┘", attr)

    def ajustar_tamano(self):
        """Sin leer teclas de curses no llega KEY_RESIZE: se compara el tamaño real del terminal (cambio de
        fuente de la consola, ventana SSH redimensionada) y se avisa a curses."""
        try:
            real = os.get_terminal_size(sys.__stdout__.fileno())
        except OSError:
            return
        if (real.lines, real.columns) != self.p.getmaxyx():
            self.c.resizeterm(real.lines, real.columns)

    def dibujar(self, interp, controles=None):
        c, p = self.c, self.p
        self.ajustar_tamano()
        p.erase()
        alto, ancho = p.getmaxyx()
        if not self.cabe():
            self._escribir(0, 0, f"Ventana demasiado pequeña ({ancho}x{alto}); se necesitan {ANCHO_MINIMO}x{ALTO_MINIMO}.")
            self._escribir(1, 0, interp.estado())
            p.refresh()
            return
        titulo = titulo_ventana(self.titulo, controles)
        self._escribir(0, (ancho - len(titulo)) // 2, titulo, c.color_pair(4) | c.A_BOLD)
        y = self._teclado(2, interp, controles)
        x1 = (ancho - ANCHO_PANELES) // 2
        x2 = x1 + ANCHO_COLUMNA + SEPARACION
        x3 = x2 + ANCHO_COLUMNA + SEPARACION
        y1 = self._panel(y, x1, "ESTADO", lineas_estado(interp, controles))
        self._creditos(y1 + 1, x1, sonido_actual(controles))
        y2 = self._panel(y, x2, "SONIDO", lineas_sonido(controles))
        y2 += 1
        self._escribir(y2, x2, "ENTRADAS MIDI", c.color_pair(4) | c.A_BOLD)
        self._escribir(y2 + 1, x2, "─" * ANCHO_COLUMNA, c.color_pair(4))
        filas = lineas_entradas(controles, ANCHO_COLUMNA)
        for n, (texto, sel, activa, conectada) in enumerate(filas):
            attr = c.color_pair(8) | c.A_BOLD if sel else (c.color_pair(5) if conectada else c.color_pair(5) | c.A_DIM)
            self._escribir(y2 + 2 + n, x2, texto.ljust(ANCHO_COLUMNA), attr)
        auto = (controles.router or {}).get("auto_nuevas") if controles is not None else None
        if auto is not None:
            self._escribir(y2 + 2 + len(filas), x2, f"Nuevas: {'se conectan solas' if auto else 'no se conectan'}",
                           c.color_pair(5))
        for n, (tecla, accion) in enumerate(lineas_controles()):
            if n == 0:
                self._escribir(y, x3, "CONTROLES", c.color_pair(4) | c.A_BOLD)
                self._escribir(y + 1, x3, "─" * ANCHO_COLUMNA, c.color_pair(4))
            self._escribir(y + 2 + n, x3, f"{tecla:9s}", c.color_pair(4))
            self._escribir(y + 2 + n, x3 + 9, accion, c.color_pair(5) | c.A_BOLD)
        if interp.menu.abierto:
            self._menu(lineas_menu(interp.menu))
        elif interp.menu_salida.abierto:
            self._menu(lineas_menu_salidas(interp.menu_salida))
        modal = lineas_modal(controles, menu_abierto=interp.menu.abierto or interp.menu_salida.abierto)
        if modal:
            self._modal(modal)
        if interp.confirmar.abierto:          # encima de todo: es lo único que atiende el teclado
            self._modal(LINEAS_APAGAR)
        p.refresh()


def bucle(fds, salida, interprete, redibujar=None, refresco=0.1, controles=None):
    """Lee eventos de tecla de uno o varios descriptores (las interfaces del teclado) y envía MIDI hasta ESC
    (devuelve "salir"), F12 confirmado ("apagar") o fin de una entrada ("fin"). Lo que no es MIDI va a
    controles.aplicar().
    redibujar(interprete) se llama tras cada lote de eventos y periódicamente (notas del teclado MIDI, estado del
    sistema, cambios de tamaño). Una tecla notificada por dos interfaces no suena dos veces (Interprete)."""
    import select
    fds = [fds] if isinstance(fds, int) else list(fds)
    lectores = {fd: LectorEvdev() for fd in fds}
    while True:
        if controles is not None:
            controles.actualizar_sistema()
        if redibujar:
            redibujar(interprete)
        listos, _, _ = select.select(fds, [], [], refresco)
        if not listos:
            continue
        eventos = []
        for fd in listos:
            datos = os.read(fd, TAM_EVDEV * 64)
            if not datos:
                return "fin"
            eventos += lectores[fd].alimentar(datos)
        for codigo, valor in eventos:
            for m in interprete.evento(codigo, valor):
                if m[0] in ("salir", "apagar"):
                    return m[0]
                if m[0] in ("on", "off", "cc"):
                    salida.enviar(m)
                elif controles is not None:
                    controles.aplicar(m)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Teclado de computador como teclado de piano (MIDI).")
    ap.add_argument("--dispositivo", help="evdev del teclado (por defecto, autodetección)")
    ap.add_argument("--octava", type=int, default=4)
    ap.add_argument("--fuerza", type=int, default=80)
    ap.add_argument("--sin-captura", action="store_true", help="no capturar el teclado en exclusiva")
    ap.add_argument("--entrada-prueba", help="archivo de eventos evdev en lugar del teclado (pruebas)")
    ap.add_argument("--pausa-inicial", type=float, default=0.0, help="segundos de espera antes de leer")
    ap.add_argument("--nombre-cliente", default="Teclado Piano")
    ap.add_argument("--interfaz", choices=("auto", "pantalla", "linea"), default="auto",
                    help="pantalla completa (curses), una línea de estado, o auto (pantalla si hay terminal)")
    ap.add_argument("--titulo", default="Piano - Raspberry Pi")
    ap.add_argument("--estado", default=os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "piano-vivo.estado"),
                    help="archivo de estado de piano-en-vivo.sh (enrutador y reverb)")
    ap.add_argument("--sin-controles", action="store_true", help="sin volumen/enrutador/sistema (pruebas)")
    args = ap.parse_args(argv)

    ruta = args.entrada_prueba or args.dispositivo or buscar_teclado()
    if not ruta:
        print("ERROR: no se encontró ningún teclado en /dev/input/by-id", file=sys.stderr)
        return 1
    rutas = [ruta] if args.entrada_prueba else dispositivos_del_teclado(ruta)
    salida = SalidaSeq(args.nombre_cliente)
    controles = None if args.sin_controles else Controles.desde_estado(args.estado)
    interprete = Interprete(args.octava, args.fuerza, instrumentos=controles.instrumentos if controles else None,
                            salidas=controles.salidas if controles else None)
    fds = [os.open(r, os.O_RDONLY | os.O_NONBLOCK if not args.entrada_prueba else os.O_RDONLY) for r in rutas]
    capturado = False
    hay_terminal = sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb"
    pantalla = args.interfaz == "pantalla" or (args.interfaz == "auto" and hay_terminal)
    try:
        if not args.entrada_prueba and not args.sin_captura:
            import fcntl
            for fd in fds:
                fcntl.ioctl(fd, EVIOCGRAB, 1)    # lo tecleado deja de llegar a la consola
            capturado = True
        extra = f" (+ {', '.join(os.path.basename(r) for r in rutas[1:])})" if len(rutas) > 1 else ""
        print(f"== Teclado: {ruta}{extra}{' (capturado)' if capturado else ''} -> MIDI "
              f"{args.nombre_cliente}:notas (cliente ALSA {salida.cliente})")
        print(AYUDA, flush=True)
        if args.pausa_inicial:
            time.sleep(args.pausa_inicial)
        if pantalla:
            import curses
            import locale
            locale.setlocale(locale.LC_ALL, "")

            def con_pantalla(scr):
                vista = VistaTexto(scr, args.titulo)
                return bucle(fds, salida, interprete, lambda i: vista.dibujar(i, controles), controles=controles)
            resultado = curses.wrapper(con_pantalla)
        else:
            def linea(interp):
                if hay_terminal:
                    print("\r" + interp.estado() + "   ", end="", flush=True)
            resultado = bucle(fds, salida, interprete, linea, controles=controles)
        print(f"\n== {({'salir': 'Salir (ESC)', 'apagar': 'Apagar (F12)'}).get(resultado, 'Fin de la entrada')}")
        return CODIGO_APAGAR if resultado == "apagar" else 0
    except KeyboardInterrupt:
        return 0
    finally:
        if controles is not None:
            controles.aplicar_volumen(forzar=True)   # el último paso de volumen no se pierde al salir
        for m in interprete.apagar_todo():   # nunca dejar notas colgadas ni el pedal pisado
            try:
                salida.enviar(m)
            except OSError:
                pass
        for fd in fds:
            if capturado:
                try:
                    import fcntl
                    fcntl.ioctl(fd, EVIOCGRAB, 0)
                except OSError:
                    pass
            os.close(fd)
        salida.cerrar()


if __name__ == "__main__":
    sys.exit(main())
