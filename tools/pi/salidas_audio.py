#!/usr/bin/env python3
"""Salidas de audio del piano (fase 10): qué tarjetas hay, cuál usar y cómo enlazar la reverb a ella.

- Las salidas son los nodos «Audio/Sink» de PipeWire (pw-dump): tarjetas USB, la salida de auriculares de la Pi, el
  HDMI y cualquier otra (p. ej. salidas virtuales de las pruebas).
- Frecuencias: PipeWire las da como rango; de una tarjeta USB se lee además la lista exacta de /proc/asound.
- Elección: la preferida si está; si no, otra USB; si no, una de la Pi. Se avisa cuando no es la preferida.
- Tasa del piano: 44100 Hz si la salida la admite (la G1 solo admite esa); si no, 48000 Hz.
- Una salida que el piano deja se suspende enseguida (suspender_si_libre): WirePlumber 0.4.13 cae si no.

Uso (para el motor):
  salidas_audio.py elegir [--preferencias JSON]   -> «node.name<TAB>tasa<TAB>aviso» (código 1 si no hay ninguna)
  salidas_audio.py lista                          -> tabla de las salidas conectadas
  salidas_audio.py suspender NODE.NAME            -> la suspende si quedó libre (espera hasta 2 s a que lo esté)
  salidas_audio.py esperar [--preferencias JSON] [--segundos N]
                                                  -> al encender (fase 11): espera hasta N s (20) a la preferida
                                                     (sin preferida, a alguna USB); código 1 si no llegó
Variables: PIANO_SALIDA (preferida, por encima de las preferencias), PIANO_SOLO_SALIDAS (nombres separados por
comas: solo esas se consideran; las pruebas lo usan para no tocar nunca una tarjeta real).
"""
import json
import os
import re
import subprocess
import sys

TASA_PREFERIDA = 44100
TASA_ALTERNATIVA = 48000
VOLUMEN_PRIMERA_VEZ = 0.40       # tope del volumen la primera vez que el piano usa una tarjeta
AVISO_PI = "salida de la Pi: calidad limitada"
AVISO_HDMI = "HDMI: el sonido sale por la pantalla"
ORDEN_TIPOS = ("usb", "pi", "hdmi", "otra")       # orden de la lista y de la alternativa si falta la preferida
NOMBRES_PI = {"pi": "Auriculares de la Pi (3,5 mm)", "hdmi": "HDMI (por la pantalla)"}
RUTA_PREFERENCIAS = os.path.expanduser("~/.config/piano/preferencias.json")


def tipo_de(nombre, props):
    """usb | pi (auriculares de 3,5 mm) | hdmi | otra."""
    ruta = props.get("api.alsa.path", "")
    tarjeta = props.get("api.alsa.card.name", "")
    if ".usb-" in nombre or props.get("device.bus") == "usb":
        return "usb"
    if "hdmi" in nombre.lower() or "hdmi" in ruta.lower() or "hdmi" in tarjeta.lower():
        return "hdmi"
    if "bcm2835" in tarjeta.lower() or "bcm2835" in props.get("node.nick", "").lower():
        return "pi"
    return "otra"


def nombre_visible(props, nombre):
    d = props.get("node.description") or props.get("node.nick") or nombre
    return re.sub(r"\s+(Analog|Digital) Stereo(\s*\(HDMI\))?$", "", d).strip() or nombre


def tasas_de_formato(params):
    """Tasas admitidas según los EnumFormat de PipeWire: (conjunto exacto o None, rango (min, max) o None)."""
    exactas, rango = set(), None
    for f in params.get("EnumFormat") or []:
        r = f.get("rate")
        if isinstance(r, int):
            exactas.add(r)
        elif isinstance(r, dict):
            if "min" in r and "max" in r:
                lo, hi = int(r["min"]), int(r["max"])
                rango = (min(lo, rango[0]), max(hi, rango[1])) if rango else (lo, hi)
            elif "default" in r:
                exactas.add(int(r["default"]))
            for k, v in r.items():
                if k.startswith("alt") and isinstance(v, int):
                    exactas.add(v)
    return (exactas or None), rango


def tasas_usb(ruta_alsa, raiz="/proc/asound"):
    """Lista exacta de tasas de reproducción de una tarjeta USB (p. ej. api.alsa.path «front:2» -> card2/stream0)."""
    m = re.search(r":(\d+)", ruta_alsa or "")
    if not m:
        return None
    try:
        with open(os.path.join(raiz, f"card{m.group(1)}", "stream0"), encoding="utf-8") as f:
            texto = f.read()
    except OSError:
        return None
    reproduccion = texto.split("Capture:")[0]
    tasas = set()
    for linea in re.findall(r"Rates:\s*(.+)", reproduccion):
        tasas.update(int(x) for x in re.findall(r"\d+", linea))
    return tasas or None


def admite(salida, tasa):
    if salida.get("tasas") is not None:
        return tasa in salida["tasas"]
    if salida.get("rango") is not None:
        return salida["rango"][0] <= tasa <= salida["rango"][1]
    return True          # sin datos: PipeWire convierte si hace falta


def tasa_para(salida):
    return TASA_PREFERIDA if admite(salida, TASA_PREFERIDA) else TASA_ALTERNATIVA


def salidas_de(objetos, raiz_asound="/proc/asound"):
    """Lista de salidas (dict) a partir de pw-dump: id (objeto), nombre (node.name), visible, tipo, tasas, rango,
    aviso. Ordenadas: USB primero, después la Pi, el HDMI y otras; dentro de cada tipo, por nombre visible."""
    lista = []
    for o in objetos:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") != "Audio/Sink":
            continue
        nombre = props.get("node.name", "")
        if not nombre:
            continue
        tipo = tipo_de(nombre, props)
        exactas, rango = tasas_de_formato(info.get("params") or {})
        if tipo == "usb":
            exactas = tasas_usb(props.get("api.alsa.path", ""), raiz_asound) or exactas
        visible = NOMBRES_PI.get(tipo) or nombre_visible(props, nombre)
        s = {"id": o.get("id"), "nombre": nombre, "visible": visible, "tipo": tipo,
             "tasas": sorted(exactas) if exactas else None, "rango": list(rango) if rango else None}
        s["aviso"] = {"pi": AVISO_PI, "hdmi": AVISO_HDMI}.get(tipo)
        lista.append(s)
    lista.sort(key=lambda s: (ORDEN_TIPOS.index(s["tipo"]), s["visible"].lower(), s["nombre"]))
    return lista


def filtrar(salidas, solo=None):
    """Solo las salidas permitidas (PIANO_SOLO_SALIDAS en las pruebas)."""
    if not solo:
        return salidas
    permitidas = {x.strip() for x in solo.split(",") if x.strip()}
    return [s for s in salidas if s["nombre"] in permitidas]


def elegir(salidas, preferida=None):
    """(salida, aviso): la preferida si está; si no, la primera de la lista (USB primero) y un aviso. (None, aviso)
    si no hay ninguna."""
    if not salidas:
        return None, "no hay ninguna salida de audio: conecta una tarjeta de sonido"
    for s in salidas:
        if s["nombre"] == preferida:
            return s, None
    s = salidas[0]
    if preferida:
        return s, f"la salida elegida no está conectada: se usa {s['visible']}"
    return s, None


AVISO_DESCONECTADA = "salida desconectada: vuelve a conectarla o elige otra con F10"
ERROR_ENLAZAR = "no se pudo enlazar la salida"
ESPERA_REINTENTO = 5     # vueltas de verificar() (una por segundo) entre reintentos de enlazar una salida que falló


class GestorSalida:
    """Salida activa del piano, en caliente. Sin E/S: recibe las salidas detectadas, las órdenes de la interfaz y
    lo que el enrutador comprueba; devuelve efectos que el enrutador ejecuta:
      ("enlazar", nombre)                 enlazar la reverb a esa salida
      ("soltar", nombre)                  quitar los enlaces de la reverb a esa salida
      ("comprobar", nombre)               ¿quedó enlazada? -> el enrutador llama a confirmar(ok)
      ("volumen", nombre)                 aplicar el volumen recordado (o el tope de la primera vez): volumen_para()
      ("guardar_volumen", nombre)         leer su volumen y recordarlo: registrar_volumen()
      ("nodo_cortes", viejo, nuevo)       vigilar los cortes del nodo nuevo en lugar del viejo
      ("suspender", nombre)               la que se dejó: suspenderla en cuanto quede libre (suspender_si_libre)
    Conectar antes de cortar: la anterior se suelta solo cuando la nueva está confirmada. La reverb tiene además el
    ancla siempre enlazada: aunque se desconecte la tarjeta, sus salidas nunca quedan sin enlaces.
    verificar(): si la reverb pierde los enlaces a la activa sin que esta desaparezca (pasa cuando WirePlumber se
    reinicia: PipeWire deshace los enlaces de los nodos que él configura), se rehacen como en una reconexión."""

    def __init__(self, prefs, activa, tasa, aviso=None):
        self.prefs = prefs
        self.prefs.setdefault("volumen_salidas", {})
        self.activa = activa
        self.tasa = tasa
        self.aviso = aviso
        self.salidas = []
        self.estado = "lista"        # lista | cambiando | desconectada
        self.destino = None          # salida a la que se está cambiando
        self.error = None            # resultado de la última orden que no se pudo cumplir
        self.cambios_prefs = False
        self.espera_reintento = 0    # vueltas de verificar() que faltan para reintentar tras un enlace fallido

    def _salida(self, nombre):
        return next((s for s in self.salidas if s["nombre"] == nombre), None)

    def salida(self, nombre):
        """La salida detectada con ese nombre (dict) o None."""
        return self._salida(nombre)

    def inicio(self):
        return [("volumen", self.activa)]

    def actualizar(self, salidas):
        """Nueva detección de salidas: desconexión y reconexión de la activa."""
        self.salidas = list(salidas)
        presente = self._salida(self.activa) is not None
        if self.estado == "lista" and not presente:
            self.estado, self.aviso = "desconectada", AVISO_DESCONECTADA
            return []
        if self.estado == "desconectada" and presente:
            self.estado, self.destino = "cambiando", self.activa
            return [("enlazar", self.activa), ("comprobar", self.activa)]
        if self.estado == "cambiando" and self._salida(self.destino) is None:
            self.estado, self.error = ("desconectada" if not presente else "lista"), "la salida se desconectó al cambiar"
            self.destino = None
        return []

    def verificar(self, enlazada):
        """Comprobación de cada segundo: ¿sigue la reverb enlazada a la activa? Si no y la activa está conectada, se
        vuelve a enlazar (como al reconectarla). Tras un intento fallido se espera ESPERA_REINTENTO vueltas."""
        if enlazada or self.estado not in ("lista", "desconectada") or self._salida(self.activa) is None:
            return []
        if self.espera_reintento > 0:
            self.espera_reintento -= 1
            return []
        self.estado, self.destino = "cambiando", self.activa
        return [("enlazar", self.activa), ("comprobar", self.activa)]

    def seleccionar(self, nombre):
        """Orden de la interfaz (F10)."""
        self.error = None
        s = self._salida(nombre)
        if s is None:
            self.error = "esa salida ya no está conectada"
            return []
        if nombre == self.activa and self.estado == "lista":
            return []
        if self.estado == "cambiando":
            self.error = "espera a que termine el cambio de salida"
            return []
        if not admite(s, self.tasa):
            self.prefs["salida"] = nombre
            self.cambios_prefs = True
            self.error = (f"{s['visible']} necesita {tasa_para(s) // 1000} kHz: se usará al volver a abrir el piano")
            return []
        self.estado, self.destino = "cambiando", nombre
        efectos = [("guardar_volumen", self.activa)] if self._salida(self.activa) else []
        return efectos + [("enlazar", nombre), ("comprobar", nombre)]

    def confirmar(self, ok):
        """Resultado de «comprobar»: con la nueva enlazada se suelta la anterior y se aplica su volumen."""
        if self.estado != "cambiando":
            return []
        nueva, vieja = self.destino, self.activa
        self.destino = None
        if not ok:
            self.estado = "lista" if self._salida(vieja) and vieja != nueva else "desconectada"
            self.error = ERROR_ENLAZAR
            if nueva == vieja:
                self.espera_reintento = ESPERA_REINTENTO
            return [("soltar", nueva)] if nueva != vieja else []
        self.activa, self.estado, self.aviso = nueva, "lista", None
        self.espera_reintento = 0
        if self.error == ERROR_ENLAZAR:
            self.error = None
        if self.prefs.get("salida") != nueva:
            self.prefs["salida"] = nueva
            self.cambios_prefs = True
        efectos = []
        if vieja != nueva:
            efectos += [("soltar", vieja), ("nodo_cortes", vieja, nueva)]
        efectos.append(("volumen", nueva))
        if vieja != nueva and self._salida(vieja) is not None:
            efectos.append(("suspender", vieja))
        return efectos

    def volumen_para(self, nombre, actual):
        """Volumen a aplicar a una salida: el recordado; la primera vez, el actual con un tope de 40 %."""
        guardado = self.prefs["volumen_salidas"].get(nombre)
        if isinstance(guardado, (int, float)) and not isinstance(guardado, bool) and 0 <= guardado <= 1.5:
            return round(float(guardado), 2)
        valor = round(min(actual if actual is not None else VOLUMEN_PRIMERA_VEZ, VOLUMEN_PRIMERA_VEZ), 2)
        self.registrar_volumen(nombre, valor)
        return valor

    def registrar_volumen(self, nombre, valor):
        if nombre is None or valor is None:
            return False
        valor = round(float(valor), 2)
        if self.prefs["volumen_salidas"].get(nombre) == valor:
            return False
        self.prefs["volumen_salidas"][nombre] = valor
        self.cambios_prefs = True
        return True

    def estado_publico(self):
        activa = self._salida(self.activa)
        lista = []
        for s in self.salidas:
            aviso = s["aviso"]
            if not admite(s, self.tasa):
                aviso = f"necesita {tasa_para(s) // 1000} kHz: al volver a abrir"
            lista.append({"nombre": s["nombre"], "visible": s["visible"], "tipo": s["tipo"], "aviso": aviso,
                          "activa": s["nombre"] == self.activa})
        destino = self._salida(self.destino) if self.destino else None
        return {"estado": self.estado, "aviso": self.aviso, "error": self.error, "tasa": self.tasa,
                "activa": {"nombre": self.activa, "visible": activa["visible"] if activa else self.activa,
                           "id": activa["id"] if activa else None, "tipo": activa["tipo"] if activa else None},
                "destino": destino["visible"] if destino else None, "lista": lista}


def leer_pw_dump(ejecutar=subprocess.run):
    r = ejecutar(["pw-dump"], capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout or "[]")


def puertos_de(nombre, lineas_pw_link_i):
    """Puertos de entrada de una salida, de `pw-link -i`: los FL/FR primero (estéreo), en orden."""
    pref = nombre + ":"
    puertos = [l.strip() for l in lineas_pw_link_i if l.strip().startswith(pref)]
    reproduccion = [p for p in puertos if p[len(pref):].startswith("playback_")]
    orden = {"FL": 0, "FR": 1}
    return sorted(reproduccion or puertos, key=lambda p: (orden.get(p.rsplit("_", 1)[-1], 9), p))


def destinos_de(lineas_pw_link_l, puerto):
    """Destinos de un puerto de salida según `pw-link -l` (como destinos_de de lib-pw.sh)."""
    destinos, dentro = [], False
    for linea in lineas_pw_link_l:
        if linea.rstrip() == puerto:
            dentro = True
            continue
        if linea and not linea[0].isspace():
            dentro = False
        elif dentro and "|->" in linea:
            destinos.append(linea.split("|->", 1)[1].strip())
    return destinos


def entradas_de(lineas_pw_link_iIl):
    """Entradas de PipeWire según `pw-link -iIl`: {puerto: (id, [orígenes enlazados])}. Cada entrada es una línea
    «  105 nodo:puerto» y, debajo, una «  114   |<-  116 otro:puerto» por enlace (id del enlace y del origen)."""
    entradas, actual = {}, None
    for linea in lineas_pw_link_iIl:
        partes = linea.strip().split(None, 1)
        if len(partes) < 2 or not partes[0].isdigit():
            continue
        resto = partes[1]
        if resto.startswith("|<-"):
            origen = resto[3:].strip().split(None, 1)
            if actual is not None and len(origen) == 2 and origen[0].isdigit():
                entradas[actual][1].append(origen[1])
            continue
        actual = resto
        entradas[actual] = (int(partes[0]), [])
    return entradas


def firma_entradas(entradas):
    """Cambia si una entrada aparece, desaparece o se recrea (otro id con el mismo nombre: p. ej. la tarjeta tras
    reiniciarse WirePlumber); no cambia con los enlaces."""
    return tuple(sorted((p, i) for p, (i, _) in entradas.items()))


def enlazada(entradas, nombre, desde):
    """¿Llegan todos los puertos `desde` (las salidas de la reverb) a alguna entrada de la salida `nombre`?"""
    pref = nombre + ":"
    origenes = {o for p, (_, os_) in entradas.items() if p.startswith(pref) for o in os_}
    return bool(desde) and all(d in origenes for d in desde)


def estado_nodo(objetos, nombre):
    """(id, estado) del nodo con ese node.name según pw-dump (estado: running, idle, suspended...), o None."""
    for o in objetos:
        info = o.get("info") or {}
        if o.get("type") == "PipeWire:Interface:Node" and (info.get("props") or {}).get("node.name") == nombre:
            return o.get("id"), info.get("state")
    return None


def suspender_si_libre(nombre, objetos, ejecutar=None):
    """Un intento de suspender la salida si quedó libre («idle»): lo mismo que hace WirePlumber tras 5 s, pero ya.
    WirePlumber 0.4.13 (el de Debian 12) cae con SIGSEGV si la salida desaparece en esos 5 s (p. ej. se desenchufa
    la tarjeta recién dejada): su suspend-node.lua no comprueba que el nodo siga existiendo (0.4.17 sí lo hace).
    -> "suspendida" | "ocupada" (aún suena o la usa otro programa) | "ya" (estaba suspendida) | "no está" | "error"."""
    e = estado_nodo(objetos, nombre)
    if e is None:
        return "no está"
    oid, estado = e
    if estado == "suspended":
        return "ya"
    if estado != "idle":
        return "ocupada"
    ejecutar = ejecutar or subprocess.run
    try:
        r = ejecutar(["pw-cli", "send-command", str(oid), "Suspend", "{}"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "error"
    # pw-cli termina con código 0 aunque falle: el error solo se ve en lo que imprime
    return "error" if r.returncode != 0 or "Error" in (r.stdout or "") + (r.stderr or "") else "suspendida"


def pares(salidas_reverb, puertos_destino):
    """[(origen, destino)]: izquierda con izquierda y derecha con derecha; si algo es mono, se reparte."""
    if not salidas_reverb or not puertos_destino:
        return []
    izq, der = salidas_reverb[0], salidas_reverb[1] if len(salidas_reverb) > 1 else salidas_reverb[0]
    d_izq, d_der = puertos_destino[0], puertos_destino[1] if len(puertos_destino) > 1 else puertos_destino[0]
    return [(izq, d_izq), (der, d_der)]


def preferida_de(ruta=RUTA_PREFERENCIAS):
    try:
        with open(ruta, encoding="utf-8") as f:
            p = json.load(f)
        s = p.get("salida") if isinstance(p, dict) else None
        return s if isinstance(s, str) and s else None
    except (OSError, ValueError):
        return None


def suspender_cli(nombre, espera=2.0, pausa=0.2, dormir=None):
    """Al cerrar el piano: la tarjeta queda libre en cuanto paran sus clientes; se espera a que esté «idle» (hasta
    `espera` s) y se suspende. Siempre termina con código 0: es una protección, no debe impedir el cierre."""
    import time
    dormir = dormir or time.sleep
    res = "error"
    for _ in range(max(1, int(espera / pausa))):
        try:
            res = suspender_si_libre(nombre, leer_pw_dump())
        except (OSError, ValueError, subprocess.SubprocessError):
            res = "error"
        if res != "ocupada":
            break
        dormir(pausa)
    print(f"{nombre}: {res}")
    return 0


def lista_para_tocar(salidas, preferida):
    """¿Se puede abrir ya el piano? Con preferida, cuando está conectada; sin ella, cuando hay alguna USB."""
    if preferida:
        return any(s["nombre"] == preferida for s in salidas)
    return any(s["tipo"] == "usb" for s in salidas)


def esperar_cli(preferida, segundos, pausa=0.5, leer=None, reloj=None, dormir=None):
    """Al encender (fase 11): PipeWire y WirePlumber arrancan con la sesión y publican las tarjetas unos segundos
    después. Se espera hasta `segundos` a la preferida (o, sin preferida, a alguna USB). 0 si llegó; 1 si no: el piano
    usará otra y lo avisará (fase 10)."""
    import time
    leer = leer or (lambda: filtrar(salidas_de(leer_pw_dump()), os.environ.get("PIANO_SOLO_SALIDAS")))
    reloj = reloj or time.monotonic
    dormir = dormir or time.sleep
    hasta = reloj() + max(0.0, float(segundos))
    print("Esperando la tarjeta de sonido...", flush=True)
    while True:
        try:
            salidas = leer()
        except (OSError, ValueError, subprocess.SubprocessError):
            salidas = []                    # PipeWire aún arrancando
        if lista_para_tocar(salidas, preferida):
            s = next((x for x in salidas if x["nombre"] == preferida), None) or \
                next(x for x in salidas if x["tipo"] == "usb")
            print(f"   lista: {s['visible']}", flush=True)
            return 0
        if reloj() >= hasta:
            print(f"   no apareció en {segundos:g} s: el piano usará otra y lo avisará", flush=True)
            return 1
        dormir(pausa)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("elegir", "lista", "suspender", "esperar") \
            or (argv[0] == "suspender" and len(argv) < 2):
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        return 2
    if argv[0] == "suspender":
        return suspender_cli(argv[1])
    ruta_prefs = RUTA_PREFERENCIAS
    if "--preferencias" in argv:
        ruta_prefs = argv[argv.index("--preferencias") + 1]
    if argv[0] == "esperar":
        try:
            segundos = float(argv[argv.index("--segundos") + 1]) if "--segundos" in argv else 20.0
        except (IndexError, ValueError):
            print("ERROR: --segundos necesita un número", file=sys.stderr)
            return 2
        return esperar_cli(os.environ.get("PIANO_SALIDA") or preferida_de(ruta_prefs), segundos)
    try:
        salidas = filtrar(salidas_de(leer_pw_dump()), os.environ.get("PIANO_SOLO_SALIDAS"))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"ERROR: no se pudo consultar PipeWire: {e}", file=sys.stderr)
        return 1
    if argv[0] == "lista":
        for s in salidas:
            tasas = ",".join(str(t) for t in s["tasas"]) if s["tasas"] else (f"{s['rango'][0]}-{s['rango'][1]}" if s["rango"] else "?")
            print(f"{s['tipo']:5} {tasa_para(s):6} {s['visible']:32} {tasas:28} {s['nombre']}")
        return 0
    preferida = os.environ.get("PIANO_SALIDA") or preferida_de(ruta_prefs)
    s, aviso = elegir(salidas, preferida)
    if s is None:
        print(f"ERROR: {aviso}", file=sys.stderr)
        return 1
    print(f"{s['nombre']}\t{tasa_para(s)}\t{aviso or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
