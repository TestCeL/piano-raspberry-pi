#!/usr/bin/env python3
"""Enrutador MIDI del piano: une el teclado de computador y los teclados MIDI elegidos y los envía al
sintetizador, con transposición y curva de fuerza. Corre dentro del motor (también sin interfaz).

- Entradas: suscripciones ALSA a las fuentes activas (se detectan y conectan/desconectan en caliente).
- Salida: puerto ALSA "Piano Enrutador:salida" (el motor lo enlaza a sfizz por PipeWire).
- Órdenes (una por línea) por un FIFO: transponer, curva, latencia, reverb, fuente, auto, panico, instrumento.
- Cambio de instrumento en caliente (fase 07): órdenes a sfizz_jack por su FIFO (load_instrument, set_cc,
  set_volume) y confirmación leyendo su salida (--salida-sintetizador, p. ej. journalctl -f de su unidad).
- Estado en JSON (para la interfaz): fuentes, notas sonando, pedal, ajustes, cortes (xruns), instrumento.
- Preferencias en ~/.config/piano/preferencias.json (se guardan al cambiar y se restauran al arrancar).

Uso: enrutador_midi.py --ordenes FIFO --estado JSON [--ctl-reverb FIFO] [--nodo-xruns piano-vivo]
                       [--ctl-sintetizador FIFO --salida-sintetizador CMD --instrumento-inicial ID]
     enrutador_midi.py --pref CLAVE        (imprime una preferencia y termina; para el motor)
"""
import argparse
import json
import os
import re
import signal
import sys
import time

import catalogo_instrumentos as cat

CURVAS = ("suave", "normal", "dura")
GAMMA = {"suave": 0.6, "normal": 1.0, "dura": 1.6}     # v' = 127 * (v/127)^gamma
LATENCIAS = (128, 256, 512, 1024)
TRANSPOSICION_MAX = 12
NOMBRE_TECLADO_PC = "Teclado Piano"
NOMBRE_PROPIO = "Piano Enrutador"
PREFERENCIAS_DEFECTO = {
    "transposicion": 0,
    "curva": "normal",
    "latencia": 512,
    "reverb": 0.35,
    "auto_nuevas": True,
    "fuentes": {},          # id ("cliente:puerto") -> activa (bool)
    "instrumento": "salamander",
    "tiempos_carga": {},    # id de instrumento -> segundos que tarda en cargar (aprendido; barra de progreso)
    "salida": "",           # salida de audio elegida (node.name de PipeWire; fase 10)
    "volumen_salidas": {},  # node.name -> volumen recordado de esa tarjeta (fase 10)
}
RUTA_PREFERENCIAS = os.path.expanduser("~/.config/piano/preferencias.json")


def curva_fuerza(vel, curva):
    if vel <= 0:
        return 0
    return max(1, min(127, round(127 * (vel / 127) ** GAMMA.get(curva, 1.0))))


def cargar_preferencias(ruta=RUTA_PREFERENCIAS):
    """Preferencias validadas (valores fuera de rango o tipos erróneos -> por defecto)."""
    p = json.loads(json.dumps(PREFERENCIAS_DEFECTO))
    try:
        with open(ruta, encoding="utf-8") as f:
            leido = json.load(f)
    except (OSError, ValueError):
        return p
    if not isinstance(leido, dict):
        return p
    t = leido.get("transposicion")
    if isinstance(t, int) and not isinstance(t, bool) and -TRANSPOSICION_MAX <= t <= TRANSPOSICION_MAX:
        p["transposicion"] = t
    if leido.get("curva") in CURVAS:
        p["curva"] = leido["curva"]
    if leido.get("latencia") in LATENCIAS:
        p["latencia"] = leido["latencia"]
    r = leido.get("reverb")
    if isinstance(r, (int, float)) and not isinstance(r, bool) and 0 <= r <= 1:
        p["reverb"] = round(float(r), 2)
    if isinstance(leido.get("auto_nuevas"), bool):
        p["auto_nuevas"] = leido["auto_nuevas"]
    if isinstance(leido.get("fuentes"), dict):
        p["fuentes"] = {str(k): bool(v) for k, v in leido["fuentes"].items() if isinstance(v, bool)}
    if isinstance(leido.get("instrumento"), str) and cat.ID_VALIDO.match(leido["instrumento"]):
        p["instrumento"] = leido["instrumento"]      # si ya no existe, el motor elige otro disponible
    if isinstance(leido.get("tiempos_carga"), dict):
        p["tiempos_carga"] = {k: round(float(v), 2) for k, v in leido["tiempos_carga"].items()
                              if isinstance(k, str) and cat.ID_VALIDO.match(k) and not isinstance(v, bool)
                              and isinstance(v, (int, float)) and 0.05 <= v <= 600}
    if isinstance(leido.get("salida"), str) and len(leido["salida"]) <= 256 and leido["salida"].isprintable():
        p["salida"] = leido["salida"]
    if isinstance(leido.get("volumen_salidas"), dict):
        p["volumen_salidas"] = {k: round(float(v), 2) for k, v in leido["volumen_salidas"].items()
                                if isinstance(k, str) and len(k) <= 256 and not isinstance(v, bool)
                                and isinstance(v, (int, float)) and 0 <= v <= 1.5}
    return p


def guardar_preferencias(prefs, ruta=RUTA_PREFERENCIAS):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, ruta)


def es_fuente(cliente, puerto, nombre_c, nombre_p, cap, propio):
    """¿Es un puerto MIDI que se puede escuchar como fuente? (excluye sistema, Midi Through, PipeWire)."""
    from alsa_seq import SEQ_PORT_CAP_READ, SEQ_PORT_CAP_SUBS_READ, SEQ_PORT_CAP_NO_EXPORT
    if cliente in (0, propio) or nombre_c in ("System", "Midi Through", NOMBRE_PROPIO):
        return False
    if nombre_c.startswith("PipeWire"):
        return False
    need = SEQ_PORT_CAP_READ | SEQ_PORT_CAP_SUBS_READ
    return (cap & need) == need and not cap & SEQ_PORT_CAP_NO_EXPORT


ESPERA_SELECCION = 0.6     # s sin nuevas pulsaciones de F6/F7 antes de cargar: se recorre la lista sin cargar cada uno
TIEMPO_MAX_CARGA = 180.0   # s sin confirmación de sfizz -> error


class GestorInstrumentos:
    """Cambio de instrumento en caliente sobre sfizz_jack (parche 0002). Sin E/S: recibe la hora y las líneas
    que imprime sfizz; devuelve las órdenes para su entrada estándar.

    Ciclo: seleccionar() -> (ESPERA_SELECCION) -> tick() devuelve load_instrument + ajustes -> sfizz imprime
    "Instrument loaded: <ruta>" -> "Volume set" (la última orden) -> listo. Si la carga falla, se vuelve a
    cargar el instrumento anterior y se informa del error.

    Mientras carga, el piano está en pausa (el enrutador no envía notas) y la interfaz muestra una barra de
    progreso estimada con el tiempo que tarda cada instrumento: el del catálogo hasta que se aprende el real
    (media entre la última medida y la anterior)."""

    def __init__(self, instrumentos, inicial, reloj=time.monotonic, tiempos=None, reloj_pared=time.time):
        self.lista = list(instrumentos)          # solo los disponibles
        self.reloj = reloj
        self.actual = cat.elegir(self.lista, inicial)    # el que tiene (o tendrá) cargado sfizz
        self.elegido = self.actual
        self.t_eleccion = None
        self.cargando = None                     # instrumento en curso
        self.fase = None                         # "carga": espera "Instrument loaded"; "ajustes": "Volume set"
        self.t_inicio = None
        self.previo = None
        self.recuperando = False
        self.error = None
        self.tiempos = dict(tiempos or {})      # id -> segundos de carga aprendidos
        self.reloj_pared = reloj_pared
        self.t_inicio_pared = None
        self.con_carga = False                  # la operación en curso incluye load_instrument
        self.ultima_duracion = None             # (id, s) de la última carga terminada, para el registro

    def desplazamiento(self):
        """Semitonos que hay que sumar a las notas para el instrumento cargado (0 si no hay)."""
        return self.actual.transposicion if self.actual is not None else 0

    def estimado(self, inst):
        return self.tiempos.get(inst.id) or inst.carga_s

    def _empezar(self, inst, cargar_sfz=True):
        self.cargando, self.fase, self.t_inicio = inst, ("carga" if cargar_sfz else "ajustes"), self.reloj()
        self.t_inicio_pared, self.con_carga = self.reloj_pared(), cargar_sfz
        return cat.ordenes_sfizz(inst, cargar_sfz)

    def iniciar(self):
        """Al arrancar el motor sfizz ya cargó el instrumento inicial (línea de órdenes): faltan sus ajustes."""
        return self._empezar(self.actual, cargar_sfz=False) if self.actual else []

    def seleccionar(self, arg):
        """"siguiente" | "anterior" | <id> (tras la pausa de selección) | "ya <id>" (en el siguiente tick: elegido
        en el menú, no hace falta esperar a que se termine de recorrer la lista)."""
        inmediato = arg.startswith("ya ")
        if inmediato:
            arg = arg[3:].strip()
        if arg in ("siguiente", "anterior"):
            base = self.elegido or self.actual
            inst = cat.vecino(self.lista, base.id if base else "", 1 if arg == "siguiente" else -1)
        else:
            inst = cat.buscar(self.lista, arg)
        if inst is None:
            return False
        self.elegido, self.t_eleccion, self.error = inst, self.reloj(), None
        if inmediato:
            self.t_eleccion -= 2 * ESPERA_SELECCION       # holgado: sin depender del redondeo
        return True

    def tick(self):
        """Órdenes para sfizz si toca empezar una carga ([] si no)."""
        ahora = self.reloj()
        if self.cargando is not None:
            if ahora - self.t_inicio > TIEMPO_MAX_CARGA:
                self.error = f"sin respuesta al cargar {self.cargando.nombre}"
                self.cargando = self.fase = None
                self.con_carga = False
                self.elegido = self.actual
            return []
        if (self.elegido is not None and self.elegido != self.actual and self.t_eleccion is not None
                and ahora - self.t_eleccion >= ESPERA_SELECCION):
            self.previo, self.recuperando = self.actual, False
            return self._empezar(self.elegido)
        return []

    def linea(self, texto):
        """Procesa una línea de la salida de sfizz. Devuelve (órdenes, evento): evento "listo" | "fallo" | None."""
        if self.cargando is None:
            return [], None
        texto = texto.rstrip()
        if self.fase == "carga":
            if "Instrument loaded: " in texto and texto.endswith(self.cargando.sfz):
                self.fase = "ajustes"
            elif "Could not load the instrument file" in texto or "Can't load instrument" in texto:
                fallido = self.cargando
                self.error = f"no se pudo cargar {fallido.nombre}"
                self.cargando = self.fase = None
                vuelta = self.previo if self.previo is not None and self.previo != fallido else None
                self.elegido = vuelta
                self.actual = None                     # sfizz quedó vacío hasta que se recupere
                if vuelta is None:
                    return [], "fallo"
                self.recuperando = True
                return self._empezar(vuelta), "fallo"
        elif self.fase == "ajustes" and "Volume set: " in texto:
            if self.con_carga:
                duracion = round(self.reloj() - self.t_inicio, 2)
                previo = self.tiempos.get(self.cargando.id)
                self.tiempos[self.cargando.id] = round(duracion if previo is None else (previo + duracion) / 2, 2)
                self.ultima_duracion = (self.cargando.id, duracion)
            self.con_carga = False
            self.actual, self.cargando, self.fase = self.cargando, None, None
            if self.elegido is None:
                self.elegido = self.actual
            if not self.recuperando:
                self.error = None
            return [], "listo"
        return [], None

    def estado(self):
        def resumen(i):
            return None if i is None else {"id": i.id, "nombre": i.nombre}
        if self.cargando is not None:
            fase = "cargando"
        elif self.elegido is not None and self.elegido != self.actual:
            fase = "elegido"
        elif self.error:
            fase = "error"
        else:
            fase = "listo"
        ids = [i.id for i in self.lista]
        carga = None
        if self.cargando is not None and self.con_carga:     # la interfaz muestra la pausa con su progreso
            despues = self.elegido if self.elegido not in (None, self.cargando) else None
            carga = {"id": self.cargando.id, "nombre": self.cargando.nombre, "inicio": self.t_inicio_pared,
                     "estimado_s": round(self.estimado(self.cargando), 2), "despues": resumen(despues)}
        return {"actual": resumen(self.actual), "elegido": resumen(self.elegido),
                "cargando": resumen(self.cargando), "estado": fase, "error": self.error, "total": len(ids),
                "posicion": ids.index(self.elegido.id) + 1 if self.elegido is not None else None,
                "carga": carga,
                "lista": [{"id": i.id, "nombre": i.nombre, "tipo": i.tipo, "autor": i.autor, "licencia": i.licencia,
                           "uso": i.uso, "restringido": i.restringido, "fuente": i.fuente} for i in self.lista]}


class Enrutador:
    """Lógica sin E/S. Los mensajes de salida son tuplas:
    ("on", nota, vel, canal) | ("off", nota, canal) | ("cc", control, valor, canal)."""

    def __init__(self, prefs=None, instrumentos=None):
        self.prefs = prefs if prefs is not None else json.loads(json.dumps(PREFERENCIAS_DEFECTO))
        self.instrumentos = instrumentos       # GestorInstrumentos o None (sin cambio de instrumento)
        self.salida = None                     # salidas_audio.GestorSalida o None (modo silencio: sin tarjeta)
        self.pedal_al_cargar = None
        self.fuentes = {}          # id -> {"cliente","puerto","tipo","conectada"}
        self.suscritas = set()     # (cliente, puerto) a los que hay suscripción
        self.mapa = {}             # (id, canal, nota_entrada) -> nota_salida
        self.sonando = {}          # nota_salida -> nº de teclas que la mantienen
        self.pedal = False
        self.ultima = None         # (nota, vel, nombre_fuente)
        self.canales = {0}
        self.cambios_prefs = False

    # --- fuentes ---------------------------------------------------------------------------
    def activa(self, fid, tipo):
        if fid in self.prefs["fuentes"]:
            return self.prefs["fuentes"][fid]
        return True if tipo == "pc" else self.prefs["auto_nuevas"]

    def actualizar_fuentes(self, detectadas):
        """detectadas: {id: (cliente, puerto, tipo)}. Devuelve (acciones, mensajes):
        acciones ("suscribir"|"desuscribir", cliente, puerto); mensajes: note off de fuentes que se van."""
        acciones, msgs = [], []
        for fid, (c, p, tipo) in detectadas.items():
            nueva = fid not in self.fuentes
            self.fuentes[fid] = {"cliente": c, "puerto": p, "tipo": tipo, "conectada": True}
            if nueva and fid not in self.prefs["fuentes"] and tipo != "pc":
                self.prefs["fuentes"][fid] = self.prefs["auto_nuevas"]   # se recuerda la decisión
                self.cambios_prefs = True
            if self.activa(fid, tipo) and (c, p) not in self.suscritas:
                acciones.append(("suscribir", c, p))
                self.suscritas.add((c, p))
            elif not self.activa(fid, tipo) and (c, p) in self.suscritas:
                acciones.append(("desuscribir", c, p))
                self.suscritas.discard((c, p))
                msgs += self.soltar_fuente(fid)
        for fid, f in self.fuentes.items():
            if fid not in detectadas and f["conectada"]:
                f["conectada"] = False
                self.suscritas.discard((f["cliente"], f["puerto"]))   # ALSA ya quitó la suscripción
                msgs += self.soltar_fuente(fid)
        return acciones, msgs

    def soltar_fuente(self, fid):
        msgs = []
        for clave in [k for k in self.mapa if k[0] == fid]:
            msgs += self._off(self.mapa.pop(clave), clave[1])
        return msgs

    def fuente_de(self, cliente, puerto):
        for fid, f in self.fuentes.items():
            if f["cliente"] == cliente and f["puerto"] == puerto and f["conectada"]:
                return fid, f["tipo"]
        return None, None

    # --- notas -----------------------------------------------------------------------------
    def _off(self, nota, canal):
        n = self.sonando.get(nota, 0)
        if n <= 1:
            self.sonando.pop(nota, None)
        else:
            self.sonando[nota] = n - 1
        return [("off", nota, canal)]

    def para_sintetizador(self, msgs):
        """Aplica la transposición propia del instrumento cargado (catálogo) a las notas que van a sfizz. La interfaz
        sigue viendo la tecla pulsada; las notas que quedarían fuera de 0..127 no se envían."""
        d = self.instrumentos.desplazamiento() if self.instrumentos is not None else 0
        if not d:
            return msgs
        salida = []
        for m in msgs:
            if m[0] in ("on", "off"):
                nota = m[1] + d
                if not 0 <= nota <= 127:
                    continue
                m = (m[0], nota) + tuple(m[2:])
            salida.append(m)
        return salida

    def bloqueado(self):
        """¿Piano en pausa? Mientras sfizz carga un instrumento no se le envía nada (no lee el MIDI y las notas se
        perderían a medias); el pedal se sigue registrando y se le reenvía al terminar si cambió. También, el momento
        de cambiar de tarjeta de sonido (fase 10)."""
        if self.salida is not None and self.salida.estado == "cambiando":
            return True
        return self.instrumentos is not None and self.instrumentos.cargando is not None

    def nota_on(self, fid, tipo, canal, nota, vel):
        if vel == 0:
            return self.nota_off(fid, canal, nota)
        if self.bloqueado():
            return []
        clave = (fid, canal, nota)
        msgs = []
        if clave in self.mapa:                  # re-pulsación sin note off previo
            msgs += self._off(self.mapa.pop(clave), canal)
        salida = nota + self.prefs["transposicion"]
        if not 0 <= salida <= 127:
            return msgs
        v = vel if tipo == "pc" else curva_fuerza(vel, self.prefs["curva"])
        self.mapa[clave] = salida
        self.sonando[salida] = self.sonando.get(salida, 0) + 1
        self.canales.add(canal)
        nombre = fid.split(":")[0] if fid else "?"
        self.ultima = (salida, v, nombre)
        return msgs + [("on", salida, v, canal)]

    def nota_off(self, fid, canal, nota):
        # Se apaga la nota que sonó, aunque la transposición haya cambiado entretanto.
        salida = self.mapa.pop((fid, canal, nota), None)
        return [] if salida is None else self._off(salida, canal)

    def control(self, canal, param, valor):
        if param == 64:
            self.pedal = valor >= 64
        self.canales.add(canal)
        if self.bloqueado():
            return []
        return [("cc", param, valor, canal)]

    def soltar_notas(self):
        """Note off de todo lo que suena (antes de cambiar de instrumento), sin tocar el pedal."""
        msgs = [("off", salida, canal) for (_, canal, _), salida in self.mapa.items()]
        self.mapa.clear()
        self.sonando.clear()
        return msgs

    # --- instrumento -------------------------------------------------------------------------
    def tick(self):
        """Periódico. Devuelve (efectos, mensajes); efectos: ("sintetizador", [órdenes para sfizz])."""
        if self.instrumentos is None:
            return [], []
        ordenes = self.instrumentos.tick()
        if not ordenes:
            return [], []
        self.pedal_al_cargar = self.pedal
        return [("sintetizador", ordenes)], self.soltar_notas()

    def linea_sintetizador(self, texto):
        if self.instrumentos is None:
            return [], []
        ordenes, evento = self.instrumentos.linea(texto)
        efectos = [("sintetizador", ordenes)] if ordenes else []
        msgs = []
        if evento == "listo":
            if self.prefs.get("instrumento") != self.instrumentos.actual.id:
                self.prefs["instrumento"] = self.instrumentos.actual.id
                self.cambios_prefs = True
            if self.instrumentos.ultima_duracion:
                iid, duracion = self.instrumentos.ultima_duracion
                self.instrumentos.ultima_duracion = None
                self.prefs.setdefault("tiempos_carga", {})[iid] = self.instrumentos.tiempos[iid]
                self.cambios_prefs = True
                efectos.append(("registro", f"INSTRUMENTO {iid} cargado en {duracion:.1f} s"))
            # Mientras carga, sfizz no lee el MIDI: si el pedal cambió entretanto, se le envía su estado real.
            if self.pedal_al_cargar is not None and self.pedal_al_cargar != self.pedal:
                msgs = [("cc", 64, 127 if self.pedal else 0, canal) for canal in sorted(self.canales)]
            self.pedal_al_cargar = None
        return efectos, msgs

    def panico(self):
        msgs = []
        for (fid, canal, _), salida in list(self.mapa.items()):
            msgs.append(("off", salida, canal))
        self.mapa.clear()
        self.sonando.clear()
        self.pedal = False
        for canal in sorted(self.canales):
            msgs += [("cc", 64, 0, canal), ("cc", 123, 0, canal), ("cc", 120, 0, canal)]
        return msgs

    # --- órdenes -----------------------------------------------------------------------------
    def orden(self, linea):
        """Aplica una orden de texto. Devuelve (efectos, mensajes). Efectos: ("latencia", N),
        ("reverb", x), ("suscribir"|"desuscribir", c, p). Marca cambios de preferencias."""
        partes = linea.strip().split(None, 1)
        if not partes:
            return [], []
        cmd, arg = partes[0].lower(), (partes[1].strip() if len(partes) > 1 else "")
        p = self.prefs
        efectos, msgs = [], []
        if cmd == "transponer":
            if arg in ("+1", "-1"):
                nuevo = p["transposicion"] + int(arg)
            else:
                try:
                    nuevo = int(arg.lstrip("="))
                except ValueError:
                    return [], []
            p["transposicion"] = max(-TRANSPOSICION_MAX, min(TRANSPOSICION_MAX, nuevo))
        elif cmd == "curva":
            if arg == "siguiente":
                p["curva"] = CURVAS[(CURVAS.index(p["curva"]) + 1) % len(CURVAS)]
            elif arg in CURVAS:
                p["curva"] = arg
            else:
                return [], []
        elif cmd == "latencia":
            if arg == "siguiente":
                p["latencia"] = LATENCIAS[(LATENCIAS.index(p["latencia"]) + 1) % len(LATENCIAS)]
            elif arg.isdigit() and int(arg) in LATENCIAS:
                p["latencia"] = int(arg)
            else:
                return [], []
            efectos.append(("latencia", p["latencia"]))
        elif cmd == "reverb":
            try:
                v = p["reverb"] + 0.05 * int(arg) if arg in ("+1", "-1") else float(arg)
            except ValueError:
                return [], []
            p["reverb"] = round(max(0.0, min(1.0, v)), 2)
            efectos.append(("reverb", p["reverb"]))
        elif cmd == "auto":
            p["auto_nuevas"] = {"on": True, "off": False}.get(arg, not p["auto_nuevas"])
        elif cmd == "fuente":
            accion, _, fid = arg.partition(" ")
            if fid not in self.fuentes or accion not in ("on", "off", "alternar"):
                return [], []
            f = self.fuentes[fid]
            actual = self.activa(fid, f["tipo"])
            p["fuentes"][fid] = (not actual) if accion == "alternar" else (accion == "on")
            if f["conectada"]:
                c, pp = f["cliente"], f["puerto"]
                if p["fuentes"][fid] and (c, pp) not in self.suscritas:
                    self.suscritas.add((c, pp))
                    efectos.append(("suscribir", c, pp))
                elif not p["fuentes"][fid] and (c, pp) in self.suscritas:
                    self.suscritas.discard((c, pp))
                    efectos.append(("desuscribir", c, pp))
                    msgs += self.soltar_fuente(fid)
        elif cmd == "panico":
            return [], self.panico()
        elif cmd == "instrumento":
            # La preferencia se guarda cuando sfizz confirma la carga (linea_sintetizador).
            if self.instrumentos is not None:
                self.instrumentos.seleccionar(arg)
            return [], []
        elif cmd == "salida":
            # Cambio de tarjeta (fase 10): efectos de salidas_audio.GestorSalida; la preferencia la guarda el gestor.
            return (self.salida.seleccionar(arg) if self.salida is not None and arg else []), []
        else:
            return [], []
        self.cambios_prefs = True
        return efectos, msgs

    # --- estado para la interfaz -------------------------------------------------------------------
    def estado(self, extra=None):
        fuentes = []
        for fid in sorted(self.fuentes, key=lambda k: (self.fuentes[k]["tipo"] != "pc", k)):
            f = self.fuentes[fid]
            fuentes.append({"id": fid, "nombre": fid.split(":")[0], "tipo": f["tipo"],
                            "activa": self.activa(fid, f["tipo"]), "conectada": f["conectada"]})
        e = {"fuentes": fuentes, "auto_nuevas": self.prefs["auto_nuevas"],
             "transposicion": self.prefs["transposicion"], "curva": self.prefs["curva"],
             "latencia": self.prefs["latencia"], "reverb": self.prefs["reverb"],
             "sonando": sorted(self.sonando), "pedal": self.pedal,
             "ultima": list(self.ultima) if self.ultima else None}
        if self.instrumentos is not None:
            e["instrumento"] = self.instrumentos.estado()
        if self.salida is not None:
            e["salida"] = self.salida.estado_publico()
        if extra:
            e.update(extra)
        return e


EFECTOS_SALIDA = ("enlazar", "soltar", "comprobar", "volumen", "guardar_volumen", "nodo_cortes",
                  "suspender")   # fase 10
ESPERA_COMPROBAR_SALIDA = 0.4    # s entre enlazar la nueva tarjeta y comprobarlo (también: la pausa se ve)
INTERVALO_VOLUMEN_SALIDA = 5.0   # s entre lecturas del volumen de la tarjeta activa (se recuerda por tarjeta)
ESPERA_SUSPENDER_SALIDA = 0.3    # s entre soltar la tarjeta anterior y suspenderla (que PipeWire la vea libre)
INTENTOS_SUSPENDER_SALIDA = 6    # si aún no está libre, se reintenta (cada ESPERA_SUSPENDER_SALIDA)

PATRON_XRUN_GRAFO = re.compile(r"\((?P<nodo>.+)-\d+\) graph xrun [\w-]+ \((?P<omitidos>\d+) suppressed\)")
PATRON_HORA = re.compile(r"^\s*(\d{9,11}\.\d+)\s")          # journalctl -o short-unix: hora del aviso
PAUSA_LATENCIA = 2.0       # s tras un cambio de latencia (F4) cuyos cortes no se cuentan: el grafo se reconfigura


class MonitorCortes:
    """Cuenta los cortes (xruns) del piano y de su grafo (sfizz, la reverb y el reloj, la G1) y lee la carga (B/Q).

    Dos fuentes:
    - `pw-top -b` (siempre): carga del nodo principal (el primero) y, si no hay registro de PipeWire, cortes por el
      contador ERR. Un mismo corte suele marcarse a la vez en varios nodos: por instantánea se suma el MAYOR
      incremento, no la suma.
    - el registro de PipeWire (`linea_registro`, opcional): las líneas «graph xrun» del reloj. Son los cortes que se
      oyen y pw-top NO los cuenta (su ERR de la G1 sigue en 0). PipeWire omite repeticiones e indica cuántas
      («N suppressed»), así que cada línea vale 1 + N. Con esta fuente activa, el ERR de pw-top no se suma (sería
      contar dos veces el mismo corte).
    Cada corte queda como evento (n, nodos) para registrarlo con su contexto."""

    def __init__(self, nodos, reloj=time.monotonic, con_registro=False, reloj_pared=time.time):
        self.nodos = [nodos] if isinstance(nodos, str) else list(nodos)
        self.nodo = self.nodos[0]
        self.reloj = reloj
        self.ultimo = {}            # nodo -> último ERR visto (el primero es la referencia)
        self.delta = {}             # incrementos de la instantánea en curso
        self.xruns = 0
        self.t_ultimo = None
        self.bq = None
        self.eventos = []
        self.con_registro = con_registro
        self.reloj_pared = reloj_pared
        self.pausas = []            # [(desde, hasta)] en hora de reloj: cambios de latencia
        self.por_latencia = 0       # cortes no contados por coincidir con un cambio de latencia
        self.eventos_latencia = []

    def pausa(self, segundos=PAUSA_LATENCIA):
        """Los cortes de los próximos segundos no se cuentan (se anotan aparte): un cambio de latencia
        reconfigura el grafo y produce cortes breves esperados."""
        ahora = self.reloj_pared()
        self.pausas = [p for p in self.pausas if p[1] > ahora - 60] + [(ahora, ahora + segundos)]

    def _en_pausa(self, hora):
        return any(desde <= hora <= hasta for desde, hasta in self.pausas)

    def cambiar_nodo(self, viejo, nuevo):
        """Vigila los cortes de otro nodo en lugar de uno (cambio de tarjeta de sonido, fase 10). Su contador ERR
        empieza de cero: el del nodo viejo ya no se compara."""
        if viejo in self.nodos:
            self.nodos[self.nodos.index(viejo)] = nuevo
        elif nuevo not in self.nodos:
            self.nodos.append(nuevo)
        self.ultimo.pop(viejo, None)
        if self.nodo == viejo:
            self.nodo = nuevo

    def linea_registro(self, texto):
        m = PATRON_XRUN_GRAFO.search(texto)
        if not m or m.group("nodo") not in self.nodos:
            return
        n = 1 + int(m.group("omitidos"))
        h = PATRON_HORA.match(texto)
        hora = float(h.group(1)) if h else self.reloj_pared()
        if self._en_pausa(hora):
            self.por_latencia += n
            self.eventos_latencia.append((n, [m.group("nodo")]))
            return
        self.xruns += n
        self.t_ultimo = self.reloj()
        self.eventos.append((n, [m.group("nodo")]))

    def linea(self, texto):
        c = texto.split()
        if c[:2] == ["S", "ID"]:    # cabecera: empieza otra instantánea
            self._cerrar()
            return
        if len(c) < 9 or c[-1] not in self.nodos:
            return
        nombre = c[-1]
        if c[8].isdigit() and not self.con_registro:
            err = int(c[8])
            previo = self.ultimo.get(nombre)
            if previo is not None and err > previo:
                self.delta[nombre] = self.delta.get(nombre, 0) + err - previo
            self.ultimo[nombre] = err   # si baja, el nodo se reinició: nueva referencia
        if nombre == self.nodo:
            try:
                self.bq = float(c[7])
            except ValueError:
                pass

    def _cerrar(self):
        if self.delta:
            n = max(self.delta.values())
            if self._en_pausa(self.reloj_pared()):
                self.por_latencia += n
                self.eventos_latencia.append((n, sorted(self.delta)))
            else:
                self.xruns += n
                self.t_ultimo = self.reloj()
                self.eventos.append((n, sorted(self.delta)))
            self.delta = {}

    def tomar_eventos(self):
        eventos, self.eventos = self.eventos, []
        return eventos

    def tomar_eventos_latencia(self):
        eventos, self.eventos_latencia = self.eventos_latencia, []
        return eventos

    def estado(self):
        hace = None if self.t_ultimo is None else round(self.reloj() - self.t_ultimo, 1)
        return {"xruns": self.xruns, "xrun_hace": hace, "bq": self.bq, "xruns_por_latencia": self.por_latencia}


def linea_corte(n, nodos, total, estado, bq=None, temp=None, throttled=None):
    """Texto para el registro de un corte, con su contexto (para encontrar su causa en sesiones reales)."""
    inst = ((estado.get("instrumento") or {}).get("actual") or {}).get("id", "-")
    partes = [f"CORTE +{n} (total {total})", "nodos: " + ", ".join(nodos), f"instrumento {inst}",
              f"pedal {'sí' if estado.get('pedal') else 'no'}", f"notas {len(estado.get('sonando', []))}",
              f"B/Q {bq:.2f}" if bq is not None else "B/Q ?",
              f"{temp:.0f} °C" if temp is not None else "temp ?"]
    if throttled is not None:
        avisos = [t for bit, t in ((0x1, "BAJO VOLTAJE"), (0x4, "CPU LIMITADA"), (0x2, "frecuencia limitada"),
                                   (0x8, "límite de temperatura")) if throttled & bit]
        partes.append(", ".join(avisos) if avisos else "energía ok")
    return " | ".join(partes)


# --- E/S ---------------------------------------------------------------------------------------------
def leer_temperatura(ruta="/sys/class/thermal/thermal_zone0/temp"):
    try:
        with open(ruta) as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def leer_throttled():
    """Bits de `vcgencmd get_throttled` (bajo voltaje, CPU limitada...) o None si no se puede leer."""
    import subprocess
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1)
        return int(r.stdout.strip().split("=")[1], 16)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def escribir_estado(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    os.replace(tmp, ruta)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Enrutador MIDI del piano.")
    ap.add_argument("--ordenes", help="FIFO de órdenes")
    ap.add_argument("--estado", help="archivo JSON de estado para la interfaz")
    ap.add_argument("--ctl-reverb", help="FIFO de órdenes de jalv (reverb)")
    ap.add_argument("--nodo-xruns", action="append",
                    help="nodo de PipeWire cuyos cortes se cuentan; se puede repetir (el primero es el principal)")
    ap.add_argument("--registro-pipewire",
                    help="orden de shell que sigue el registro de PipeWire (p. ej. journalctl -f): cortes del grafo")
    ap.add_argument("--preferencias", default=RUTA_PREFERENCIAS)
    ap.add_argument("--pref", help="imprime una preferencia y termina")
    ap.add_argument("--sin-sistema", action="store_true",
                    help="no aplica la latencia a PipeWire (pruebas: no tocar el sistema real)")
    ap.add_argument("--ctl-sintetizador", help="FIFO de órdenes de sfizz_jack (cambio de instrumento)")
    ap.add_argument("--salida-sintetizador",
                    help="orden de shell cuya salida son las líneas que imprime sfizz (p. ej. journalctl -f)")
    ap.add_argument("--instrumento-inicial", default="", help="id del instrumento que sfizz cargó al arrancar")
    ap.add_argument("--catalogo", default=cat.RUTA_CATALOGO)
    ap.add_argument("--base-instrumentos", default=cat.BASE_INSTRUMENTOS)
    ap.add_argument("--salida", help="salida de audio en uso (node.name de PipeWire; fase 10): habilita el cambio")
    ap.add_argument("--salida-desde", action="append", default=[],
                    help="puerto que se enlaza a la salida (las salidas de la reverb); se repite: izquierda, derecha")
    ap.add_argument("--salida-tasa", type=int, default=44100, help="frecuencia de la sesión (44100 o 48000)")
    ap.add_argument("--salida-aviso", default="", help="aviso al arrancar (p. ej. se usa otra tarjeta)")
    args = ap.parse_args(argv)

    if args.pref:
        print(cargar_preferencias(args.preferencias).get(args.pref, ""))
        return 0
    if not args.ordenes or not args.estado:
        ap.error("--ordenes y --estado son obligatorios")

    import select
    import subprocess
    from alsa_seq import (ClienteSeq, SEQ_OPEN_DUPLEX, SEQ_EVENT_NOTEON, SEQ_EVENT_NOTEOFF, SEQ_EVENT_CONTROLLER,
                          SEQ_EVENT_LENGTH_MASK, SEQ_EVENT_LENGTH_FIXED, SEQ_KERNEL_CLIENT, SEQ_QUEUE_DIRECT,
                          SEQ_ADDRESS_SUBSCRIBERS, SEQ_ADDRESS_UNKNOWN, construir_evento, control_de)

    prefs = cargar_preferencias(args.preferencias)
    gestor = None
    if args.ctl_sintetizador:
        gestor = GestorInstrumentos(cat.disponibles(cat.cargar(args.catalogo, args.base_instrumentos)),
                                    args.instrumento_inicial, tiempos=prefs.get("tiempos_carga"))
    enr = Enrutador(prefs, gestor)
    if args.salida and args.salida_desde:
        import salidas_audio as sa
        enr.salida = sa.GestorSalida(prefs, args.salida, args.salida_tasa, args.salida_aviso or None)
    seq = ClienteSeq(NOMBRE_PROPIO, SEQ_OPEN_DUPLEX, no_bloqueante=True)
    p_in = seq.puerto_entrada("entrada")
    p_out = seq.puerto_salida("salida")

    if not os.path.exists(args.ordenes):
        os.mkfifo(args.ordenes, 0o600)
    fd_ordenes = os.open(args.ordenes, os.O_RDWR | os.O_NONBLOCK)      # nunca ve EOF
    pendiente_ordenes = b""

    monitor, pwtop, fd_pwtop, pendiente_pwtop = None, None, None, b""
    if args.nodo_xruns:
        monitor = MonitorCortes(args.nodo_xruns, con_registro=bool(args.registro_pipewire))
        try:
            pwtop = subprocess.Popen(["pw-top", "-b"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            fd_pwtop = pwtop.stdout.fileno()
            os.set_blocking(fd_pwtop, False)
        except OSError:
            pwtop = None

    # Salida de sfizz (confirmaciones de carga). Se lanza antes de enviarle nada para no perder ninguna línea.
    sintetizador, fd_sint, pendiente_sint = None, None, b""
    if gestor is not None and args.salida_sintetizador:
        sintetizador = subprocess.Popen(args.salida_sintetizador, shell=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        fd_sint = sintetizador.stdout.fileno()
        os.set_blocking(fd_sint, False)

    registro_pw, fd_reg, pendiente_reg = None, None, b""
    if monitor is not None and args.registro_pipewire:
        registro_pw = subprocess.Popen(args.registro_pipewire, shell=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        fd_reg = registro_pw.stdout.fileno()
        os.set_blocking(fd_reg, False)

    def anotar_cortes():
        for n, nodos in monitor.tomar_eventos():
            print(linea_corte(n, nodos, monitor.xruns, enr.estado(), monitor.bq,
                              leer_temperatura(), leer_throttled()), flush=True)
        for n, nodos in monitor.tomar_eventos_latencia():
            print(f"CORTE por cambio de latencia (no se cuenta) +{n} | nodos: {', '.join(nodos)} | "
                  f"latencia {enr.prefs['latencia']}", flush=True)

    def enviar_sintetizador(ordenes):
        try:
            fd = os.open(args.ctl_sintetizador, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return False                  # sin lector (sfizz no está): el tiempo máximo de carga lo detecta
        try:
            os.write(fd, "".join(o + "\n" for o in ordenes).encode())
        finally:
            os.close(fd)
        return True

    def emitir(msgs):
        for m in enr.para_sintetizador(msgs):
            if m[0] == "on":
                seq.enviar(("on", m[1], m[2]), p_out, m[3])
            elif m[0] == "off":
                seq.enviar(("off", m[1]), p_out, m[2])
            elif m[0] == "cc":
                seq.enviar(("cc", m[1], m[2]), p_out, m[3])

    def aplicar_efectos(efectos):
        for e in efectos:
            if e[0] == "suscribir":
                seq.conectar_desde(p_in, e[1], e[2])
            elif e[0] == "desuscribir":
                seq.desconectar_desde(p_in, e[1], e[2])
            elif e[0] == "latencia" and monitor is not None:
                monitor.pausa()
                if not args.sin_sistema:
                    subprocess.run(["pw-metadata", "-n", "settings", "0", "clock.force-quantum", str(e[1])],
                                   capture_output=True)
            elif e[0] == "latencia" and not args.sin_sistema:
                subprocess.run(["pw-metadata", "-n", "settings", "0", "clock.force-quantum", str(e[1])],
                               capture_output=True)
            elif e[0] in EFECTOS_SALIDA and enr.salida is not None:
                aplicar_salida([e])
            elif e[0] == "sintetizador" and args.ctl_sintetizador:
                enviar_sintetizador(e[1])
            elif e[0] == "registro":
                print(e[1], flush=True)
            elif e[0] == "reverb" and args.ctl_reverb:
                try:
                    fd = os.open(args.ctl_reverb, os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        os.write(fd, f"mix = {e[1]:.2f}\n".encode())
                    finally:
                        os.close(fd)
                except OSError:
                    pass

    def detectar():
        d = {}
        for c, p, nc, np_, cap, tipo_c in seq.puertos():
            if es_fuente(c, p, nc, np_, cap, seq.cliente):
                tipo = "pc" if nc == NOMBRE_TECLADO_PC else ("midi" if tipo_c == SEQ_KERNEL_CLIENT else "app")
                d[f"{nc}:{np_}"] = (c, p, tipo)
        return d

    # --- Salida de audio (fase 10): detección, cambio en caliente, volumen por tarjeta ----------------------------
    gsal = enr.salida
    comprobar_pendiente = []                 # [(nombre, hora)]: enlaces a confirmar en una vuelta posterior
    suspender_pendiente = []                 # [(nombre, hora, intento)]: tarjetas dejadas, a suspender ya

    def pw_link(*opciones):
        try:
            r = subprocess.run(["pw-link", *opciones], capture_output=True, text=True, timeout=5)
            return r.stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            return []

    def volumen_de(oid):
        try:
            r = subprocess.run(["wpctl", "get-volume", str(oid)], capture_output=True, text=True, timeout=5)
            return float(r.stdout.split()[1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    def aplicar_salida(efectos):
        for e in efectos:
            if e[0] == "enlazar":
                if monitor is not None:
                    monitor.pausa()             # el grafo se reconfigura: esos cortes breves no se cuentan
                for o, d in sa.pares(args.salida_desde, sa.puertos_de(e[1], pw_link("-i"))[:2]):
                    pw_link(o, d)
            elif e[0] == "soltar":
                lineas = pw_link("-l")
                for o in args.salida_desde:
                    for d in sa.destinos_de(lineas, o):
                        if d.startswith(e[1] + ":"):
                            pw_link("-d", o, d)
            elif e[0] == "comprobar":
                comprobar_pendiente.append((e[1], time.monotonic() + ESPERA_COMPROBAR_SALIDA))
            elif e[0] in ("volumen", "guardar_volumen"):
                s = gsal.salida(e[1])
                if s is None:
                    continue
                actual = volumen_de(s["id"])
                if e[0] == "guardar_volumen":
                    gsal.registrar_volumen(e[1], actual)
                    continue
                valor = gsal.volumen_para(e[1], actual)
                if actual is None or abs(valor - actual) > 0.004:
                    try:
                        subprocess.run(["wpctl", "set-volume", str(s["id"]), f"{valor:.2f}"], capture_output=True,
                                       timeout=5)
                    except (OSError, subprocess.SubprocessError):
                        pass
                print(f"SALIDA {e[1]}: volumen {valor:.2f}", flush=True)
            elif e[0] == "nodo_cortes" and monitor is not None:
                monitor.cambiar_nodo(e[1], e[2])
                print(f"SALIDA ahora {e[2]} (antes {e[1]})", flush=True)
            elif e[0] == "suspender":
                suspender_pendiente.append((e[1], time.monotonic() + ESPERA_SUSPENDER_SALIDA, 1))

    def suspender(pendiente):
        """La tarjeta que se dejó se suspende ya, sin los 5 s de WirePlumber (que cae si se desenchufa en ese rato)."""
        nombre, _, intento = pendiente
        if nombre == gsal.activa:
            return                              # se volvió a elegir antes de suspenderla
        try:
            res = sa.suspender_si_libre(nombre, sa.leer_pw_dump())
        except (OSError, ValueError, subprocess.SubprocessError):
            res = "error"
        if res == "ocupada" and intento < INTENTOS_SUSPENDER_SALIDA:
            suspender_pendiente.append((nombre, time.monotonic() + ESPERA_SUSPENDER_SALIDA, intento + 1))
        elif res in ("suspendida", "ocupada", "error"):
            print(f"SALIDA {nombre}: {'suspendida (quedó libre)' if res == 'suspendida' else 'no se suspendió: ' + res}",
                  flush=True)

    firma_puertos = [None]

    def detectar_salidas():
        """Cada segundo, con una sola lectura de las entradas de PipeWire (`pw-link -iIl`):
        - si alguna aparece, desaparece o se recrea (otro id con el mismo nombre), se vuelven a leer las salidas;
        - si la reverb perdió los enlaces a la tarjeta activa sin que esta desaparezca (WirePlumber se reinició:
          PipeWire deshace los enlaces de los nodos que él configura), se rehacen."""
        entradas = sa.entradas_de(pw_link("-iIl"))
        if not entradas:
            return False                        # pw-link falló: nada que concluir en esta vuelta
        firma = sa.firma_entradas(entradas)
        if firma != firma_puertos[0]:
            try:
                salidas = sa.filtrar(sa.salidas_de(sa.leer_pw_dump()), os.environ.get("PIANO_SOLO_SALIDAS"))
            except (OSError, ValueError, subprocess.SubprocessError):
                return False                    # se reintenta en la próxima vuelta (la firma no se guarda)
            firma_puertos[0] = firma
            antes = gsal.estado
            aplicar_salida(gsal.actualizar(salidas))
            if gsal.estado == "desconectada" and antes != "desconectada":
                if monitor is not None:
                    monitor.pausa()
                print(f"SALIDA desconectada: {gsal.activa}", flush=True)
        efectos = gsal.verificar(sa.enlazada(entradas, gsal.activa, args.salida_desde))
        if efectos:
            print(f"SALIDA {gsal.activa}: la reverb perdió sus enlaces; se vuelven a enlazar", flush=True)
            aplicar_salida(efectos)
        return True

    salir = []
    signal.signal(signal.SIGTERM, lambda *_: salir.append(1))
    signal.signal(signal.SIGINT, lambda *_: salir.append(1))

    sondeo = select.poll()
    for fd in seq.descriptores():
        sondeo.register(fd, select.POLLIN)
    sondeo.register(fd_ordenes, select.POLLIN)
    if fd_pwtop is not None:
        sondeo.register(fd_pwtop, select.POLLIN)
    if fd_sint is not None:
        sondeo.register(fd_sint, select.POLLIN)
    if fd_reg is not None:
        sondeo.register(fd_reg, select.POLLIN)
    if gestor is not None:
        aplicar_efectos([("sintetizador", gestor.iniciar())])
    if gsal is not None:
        detectar_salidas()
        aplicar_salida(gsal.inicio())       # volumen recordado de la tarjeta (o el tope de la primera vez)

    t_detectar = t_estado = t_volumen = 0.0
    sucio = True
    try:
        while not salir:
            ahora = time.monotonic()
            if ahora - t_detectar >= 1.0:
                acciones, msgs = enr.actualizar_fuentes(detectar())
                aplicar_efectos(acciones)
                emitir(msgs)
                if gsal is not None:
                    detectar_salidas()
                t_detectar, sucio = ahora, True
            if gsal is not None:
                for pendiente in [c for c in comprobar_pendiente if c[1] <= ahora]:
                    comprobar_pendiente.remove(pendiente)
                    ok = sa.enlazada(sa.entradas_de(pw_link("-iIl")), pendiente[0], args.salida_desde)
                    aplicar_salida(gsal.confirmar(ok))
                    sucio = True
                for pendiente in [c for c in suspender_pendiente if c[1] <= ahora]:
                    suspender_pendiente.remove(pendiente)
                    suspender(pendiente)
                if gsal.estado == "lista" and ahora - t_volumen >= INTERVALO_VOLUMEN_SALIDA:
                    s = gsal.salida(gsal.activa)
                    if s is not None:
                        gsal.registrar_volumen(gsal.activa, volumen_de(s["id"]))
                    t_volumen = ahora
            for fd, _ in sondeo.poll(200):
                if fd == fd_ordenes:
                    try:
                        pendiente_ordenes += os.read(fd_ordenes, 4096)
                    except BlockingIOError:
                        pass
                    while b"\n" in pendiente_ordenes:
                        linea, pendiente_ordenes = pendiente_ordenes.split(b"\n", 1)
                        efectos, msgs = enr.orden(linea.decode("utf-8", "replace"))
                        aplicar_efectos(efectos)
                        emitir(msgs)
                        sucio = True
                elif fd == fd_sint:
                    try:
                        datos = os.read(fd_sint, 65536)
                    except BlockingIOError:
                        datos = b""
                    if datos:
                        pendiente_sint += datos
                        *lineas, pendiente_sint = pendiente_sint.split(b"\n")
                        for l in lineas:
                            efectos, msgs = enr.linea_sintetizador(l.decode("utf-8", "replace"))
                            aplicar_efectos(efectos)
                            emitir(msgs)
                        sucio = True
                    else:
                        sondeo.unregister(fd_sint)
                        fd_sint = None
                elif fd == fd_reg:
                    try:
                        datos = os.read(fd_reg, 65536)
                    except BlockingIOError:
                        datos = b""
                    if datos:
                        pendiente_reg += datos
                        *lineas, pendiente_reg = pendiente_reg.split(b"\n")
                        for l in lineas:
                            monitor.linea_registro(l.decode("utf-8", "replace"))
                        anotar_cortes()
                        sucio = True
                    else:
                        sondeo.unregister(fd_reg)
                        fd_reg = None
                elif fd == fd_pwtop:
                    try:
                        datos = os.read(fd_pwtop, 65536)
                    except BlockingIOError:
                        datos = b""
                    if datos:
                        pendiente_pwtop += datos
                        *lineas, pendiente_pwtop = pendiente_pwtop.split(b"\n")
                        for l in lineas:
                            monitor.linea(l.decode("utf-8", "replace"))
                        anotar_cortes()
                    else:
                        sondeo.unregister(fd_pwtop)
                        fd_pwtop = None
                else:
                    for ev in seq.leer_eventos():
                        if ev.flags & SEQ_EVENT_LENGTH_MASK != SEQ_EVENT_LENGTH_FIXED:
                            continue                              # sysex y similares: se ignoran
                        fid, tipo = enr.fuente_de(ev.source.client, ev.source.port)
                        if fid is None:
                            continue
                        canal = ev.data[0]
                        if ev.type == SEQ_EVENT_NOTEON:
                            emitir(enr.nota_on(fid, tipo, canal, ev.data[1], ev.data[2]))
                        elif ev.type == SEQ_EVENT_NOTEOFF:
                            emitir(enr.nota_off(fid, canal, ev.data[1]))
                        elif ev.type == SEQ_EVENT_CONTROLLER:
                            param, valor = control_de(ev)
                            emitir(enr.control(canal, param, valor))
                        else:                                     # pitch bend, aftertouch...: tal cual
                            if enr.bloqueado():                   # (salvo con el piano en pausa)
                                continue
                            ev.source.port = p_out
                            ev.dest.client, ev.dest.port = SEQ_ADDRESS_SUBSCRIBERS, SEQ_ADDRESS_UNKNOWN
                            ev.queue = SEQ_QUEUE_DIRECT
                            seq.enviar_evento(ev)
                        sucio = True
            efectos, msgs = enr.tick()
            if efectos or msgs:
                aplicar_efectos(efectos)
                emitir(msgs)
                sucio = True
            ahora = time.monotonic()
            if enr.cambios_prefs or (gsal is not None and gsal.cambios_prefs):
                try:
                    guardar_preferencias(enr.prefs, args.preferencias)
                except OSError:
                    pass
                enr.cambios_prefs = False
                if gsal is not None:
                    gsal.cambios_prefs = False
            if (sucio and ahora - t_estado >= 0.05) or ahora - t_estado >= 1.0:
                extra = monitor.estado() if monitor else {}
                escribir_estado(args.estado, enr.estado(extra))
                t_estado, sucio = ahora, False
    finally:
        try:
            emitir(enr.panico())               # nunca dejar notas colgadas
        except OSError:
            pass
        if gsal is not None and gsal.salida(gsal.activa) is not None:   # el volumen con que se deja la tarjeta
            if gsal.registrar_volumen(gsal.activa, volumen_de(gsal.salida(gsal.activa)["id"])):
                try:
                    guardar_preferencias(enr.prefs, args.preferencias)
                except OSError:
                    pass
        if pwtop:
            pwtop.terminate()
        for proc in (sintetizador, registro_pw):
            if proc:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)        # la orden de shell y su journalctl
                except OSError:
                    pass
        os.close(fd_ordenes)
        seq.cerrar()
        try:
            os.remove(args.estado)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
