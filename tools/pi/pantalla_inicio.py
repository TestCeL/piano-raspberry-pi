#!/usr/bin/env python3
"""Pantalla de inicio del piano (fase 11), al estilo de los juegos de DOS, mientras se carga: marco doble sobre fondo
azul, el título en letras de bloques, un teclado dibujado, las etapas de la carga con una barra de progreso y los
créditos del proyecto. Solo usa caracteres que tiene la fuente de la consola de la Pi (glifos_consola.txt). No suena.

El progreso lo escriben piano-teclado.sh y piano-en-vivo.sh en un archivo (por omisión
$XDG_RUNTIME_DIR/piano-vivo.progreso), una línea por paso: «segundos<TAB>etapa[<TAB>detalle...]»
  tarjeta esperando | tarjeta lista NOMBRE | tarjeta no SEGUNDOS  (solo al encender: se espera a la tarjeta)
  inicio                                                         (se arranca el motor)
  salida NODE.NAME TASA                                          (tarjeta elegida; vacía en modo silencio)
  sonido ID                                                      (sfizz carga el sonido)
  reverb | enrutador | listo
La barra estima cada etapa: el sonido, por lo que tardó la última vez (tiempos_carga de las preferencias; si no, el
carga_s del catálogo). Termina sola con «listo» (o al aparecer el archivo --listo), y con SIGTERM si el piano falla
(piano-teclado.sh la cierra y muestra el error). Lo tecleado mientras tanto se descarta: no llega a la consola.

Uso: pantalla_inicio.py [--progreso ARCHIVO] [--listo ARCHIVO] [--maximo SEGUNDOS]
"""
import argparse
import json
import os
import signal
import sys
import time

from teclado_piano import CREDITO_PROYECTO, progreso_carga

RUNDIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
ETAPAS = (("tarjeta", "Tarjeta de sonido"), ("sonido", "Sonido"), ("reverb", "Reverb de sala"),
          ("enrutador", "Teclado y MIDI"))
# Tramos de la barra: (desde, hasta, peso en s). El del sonido es su tiempo estimado. Medidos al encender la Pi 3
# (fase 11): preparar 0,2 s, reverb 3,5 s, enrutador 0,8 s.
PESO_PREPARAR, PESO_REVERB, PESO_ENRUTADOR = 1.0, 3.5, 1.0
ESTIMADO_SONIDO_DEFECTO = 15.0
ANCHO_BARRA = 50
MARCAS = {"hecha": "■", "actual": "→", "pendiente": "·"}

# Letras de bloques (5 filas); cada «#» se dibuja con dos «█» para que se vean cuadradas en la consola.
LETRAS = {
    "P": ["####", "#  #", "####", "#   ", "#   "],
    "I": ["###", " # ", " # ", " # ", "###"],
    "A": [" ## ", "#  #", "####", "#  #", "#  #"],
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "O": [" ## ", "#  #", "#  #", "#  #", " ## "],
}


def titulo_bloques(texto="PIANO"):
    """Las 5 filas del título en letras de bloques (█), con dos columnas por punto y una letra de separación."""
    filas = []
    for f in range(5):
        partes = [LETRAS[ch][f].replace("#", "██").replace(" ", "  ") for ch in texto]
        filas.append("  ".join(partes))
    return filas


def leer_progreso(texto):
    """[(segundos, etapa, [detalles])] en orden; ignora las líneas mal formadas (p. ej. una a medio escribir)."""
    eventos = []
    for linea in texto.splitlines():
        partes = linea.split("\t")
        if len(partes) < 2 or not partes[1]:
            continue
        try:
            t = float(partes[0])
        except ValueError:
            continue
        eventos.append((t, partes[1], partes[2:]))
    return eventos


def resumen(eventos, ahora, nombre_salida=None, nombre_sonido=None, estimado=None):
    """Estado para dibujar: etapas [(etiqueta, estado, detalle)], fraccion (0..1), mensaje y listo.
    nombre_salida(node.name), nombre_sonido(id) y estimado(id) traducen los datos (por omisión, tal cual)."""
    nombre_salida = nombre_salida or (lambda n: n)
    nombre_sonido = nombre_sonido or (lambda i: i)
    estimado = estimado or (lambda i: ESTIMADO_SONIDO_DEFECTO)
    ultimo = {}
    for t, etapa, det in eventos:
        ultimo[etapa] = (t, det)
    listo = "listo" in ultimo
    det = {k: (ultimo[k][1] if k in ultimo else None) for k in ("tarjeta", "salida", "sonido")}
    sonido = (det["sonido"] or [""])[0]
    # Estado de cada etapa: hecha cuando empezó la siguiente
    siguientes = {"tarjeta": "sonido", "sonido": "reverb", "reverb": "enrutador", "enrutador": "listo"}
    empezada = {"tarjeta": "tarjeta" in ultimo or "inicio" in ultimo or "salida" in ultimo,
                "sonido": "sonido" in ultimo, "reverb": "reverb" in ultimo, "enrutador": "enrutador" in ultimo}
    etapas = []
    for clave, etiqueta in ETAPAS:
        hecha = siguientes[clave] in ultimo or (clave == "tarjeta" and "salida" in ultimo)
        estado = "hecha" if hecha else ("actual" if empezada[clave] else "pendiente")
        detalle = ""
        if clave == "tarjeta":
            if det["salida"] is not None:
                n = det["salida"][0] if det["salida"] else ""
                detalle = nombre_salida(n) if n else "ninguna (modo silencio)"
            elif det["tarjeta"] and det["tarjeta"][0] == "esperando":
                detalle = "esperando..."
            elif det["tarjeta"] and det["tarjeta"][0] == "lista" and len(det["tarjeta"]) > 1:
                detalle = det["tarjeta"][1]
        elif clave == "sonido" and sonido:
            detalle = nombre_sonido(sonido)
        etapas.append((etiqueta, estado, detalle))
    # Barra: tramos con peso; el actual avanza según su tiempo estimado (sin llegar al 100 % hasta que termina)
    tramos = [("inicio", "sonido", PESO_PREPARAR), ("sonido", "reverb", estimado(sonido) if sonido else ESTIMADO_SONIDO_DEFECTO),
              ("reverb", "enrutador", PESO_REVERB), ("enrutador", "listo", PESO_ENRUTADOR)]
    total = sum(p for _, _, p in tramos)
    hecho = 0.0
    for desde, hasta, peso in tramos:
        if hasta in ultimo:
            hecho += peso
        elif desde in ultimo:
            hecho += peso * progreso_carga(ahora - ultimo[desde][0], peso)
    fraccion = 1.0 if listo else min(0.99, hecho / total)
    if listo:
        mensaje = "¡Listo para tocar!"
    elif "enrutador" in ultimo:
        mensaje = "Conectando el teclado..."
    elif "reverb" in ultimo:
        mensaje = "Preparando la reverb de sala..."
    elif "sonido" in ultimo:
        mensaje = f"Cargando el sonido: {nombre_sonido(sonido)}..."
    elif "inicio" in ultimo or "salida" in ultimo:
        mensaje = "Preparando el piano..."
    elif det["tarjeta"] and det["tarjeta"][0] == "esperando":
        mensaje = "Esperando la tarjeta de sonido..."
    else:
        mensaje = "Encendiendo..."
    return {"etapas": etapas, "fraccion": fraccion, "mensaje": mensaje, "listo": listo}


def teclado_dibujo(octavas=2):
    """Filas de un teclado dibujado: [(x, texto, estilo)] por fila; blancas de 3 columnas y negras de 2."""
    blancas = 7 * octavas + 1
    negras_tras = (0, 1, 3, 4, 5)            # do#, re#, fa#, sol#, la# (tras la blanca 0, 1, 3, 4, 5 de la octava)
    filas = []
    for fila in range(4):
        segs = [(0, "│  " * blancas + "│", "blanca")]
        if fila < 2:
            for b in range(blancas - 1):
                if b % 7 in negras_tras:
                    segs.append(((b + 1) * 3 - 1, "  ", "negra"))
        filas.append(segs)
    return filas


def componer(ancho, alto, r):
    """Lo que se dibuja: [(y, x, texto, estilo)]. Tres tamaños: completo (título y teclado), compacto y mínimo."""
    out = []
    if ancho < 30 or alto < 8:
        return [(0, 0, f"Piano Raspberry Pi: {r['mensaje']} {round(r['fraccion'] * 100)} %"[:max(1, ancho - 1)], "mensaje")]

    def centro(y, texto, estilo):
        texto = texto[:ancho - 4]
        out.append((y, max(2, (ancho - len(texto)) // 2), texto, estilo))

    # Marco doble
    out.append((0, 0, "╔" + "═" * (ancho - 2) + "╗", "marco"))
    for y in range(1, alto - 1):
        out.append((y, 0, "║", "marco"))
        out.append((y, ancho - 1, "║", "marco"))
    out.append((alto - 1, 0, "╚" + "═" * (ancho - 2) + "╝", "marco"))
    completo = alto >= 30 and ancho >= 70
    y = 2
    if completo:
        for fila in titulo_bloques():
            centro(y, fila, "titulo")
            y += 1
        y += 1
        centro(y, "R A S P B E R R Y   P I", "subtitulo")
        y += 2
        dibujo = teclado_dibujo()
        x0 = (ancho - len(dibujo[0][0][1])) // 2
        for segs in dibujo:
            for x, texto, estilo in segs:
                out.append((y, x0 + x, texto, estilo))
            y += 1
        y += 2
    else:
        centro(y, "PIANO RASPBERRY PI", "titulo")
        y += 2
    centro(y, r["mensaje"], "mensaje")
    y += 2
    ancho_barra = max(10, min(ANCHO_BARRA, ancho - 16))
    llenos = round(r["fraccion"] * ancho_barra)
    x_barra = (ancho - ancho_barra - 6) // 2
    out.append((y, x_barra, "█" * llenos, "barra"))
    out.append((y, x_barra + llenos, "░" * (ancho_barra - llenos), "barra_vacia"))
    out.append((y, x_barra + ancho_barra, f" {round(r['fraccion'] * 100):3d} %", "mensaje"))
    y += 2
    filas = [f"{MARCAS[e]} {etiqueta:<18} {detalle}" for etiqueta, e, detalle in r["etapas"]]
    x_etapas = max(2, (ancho - max(len(f) for f in filas)) // 2)
    for (etiqueta, e, _), texto in zip(r["etapas"], filas):
        if y < alto - 3:
            out.append((y, x_etapas, texto[:ancho - x_etapas - 2], e))
        y += 1
    if alto - 3 > y - 1:
        centro(alto - 3, CREDITO_PROYECTO, "credito")
    return out


# --- Datos para traducir lo que escribe el motor ----------------------------------------------------------------
def nombres_y_estimados():
    """(nombre_sonido, estimado) desde el catálogo y las preferencias; sin ellos, el id y el tiempo por omisión."""
    nombres, cargas, tiempos = {}, {}, {}
    try:
        import catalogo_instrumentos as cat
        for i in cat.cargar(os.environ.get("PIANO_CATALOGO", cat.RUTA_CATALOGO),
                            os.environ.get("PIANO_INSTRUMENTOS", cat.BASE_INSTRUMENTOS)):
            nombres[i.id], cargas[i.id] = i.nombre, i.carga_s
    except (OSError, ValueError, ImportError):
        pass
    ruta = os.environ.get("PIANO_PREFERENCIAS", os.path.expanduser("~/.config/piano/preferencias.json"))
    try:
        with open(ruta, encoding="utf-8") as f:
            leido = json.load(f).get("tiempos_carga") or {}
        tiempos = {k: float(v) for k, v in leido.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    except (OSError, ValueError, AttributeError):
        pass
    return (lambda i: nombres.get(i, i)), (lambda i: tiempos.get(i) or cargas.get(i) or ESTIMADO_SONIDO_DEFECTO)


def nombre_salida_pipewire(nombre, cache={}):
    """Nombre visible de la tarjeta (de PipeWire, una sola vez); si no se puede, el node.name tal cual."""
    if nombre not in cache:
        cache[nombre] = nombre
        try:
            import salidas_audio as sa
            s = next((x for x in sa.salidas_de(sa.leer_pw_dump()) if x["nombre"] == nombre), None)
            if s:
                cache[nombre] = s["visible"]
        except Exception:      # noqa: BLE001 — una consulta fallida no debe tumbar la pantalla de inicio
            pass
    return cache[nombre]


def correr(scr, args):
    import curses
    curses.curs_set(0)
    curses.start_color()
    pares = {"fondo": (curses.COLOR_WHITE, curses.COLOR_BLUE, 0),
             "marco": (curses.COLOR_CYAN, curses.COLOR_BLUE, curses.A_BOLD),
             "titulo": (curses.COLOR_YELLOW, curses.COLOR_BLUE, curses.A_BOLD),
             "subtitulo": (curses.COLOR_WHITE, curses.COLOR_BLUE, curses.A_BOLD),
             "blanca": (curses.COLOR_BLACK, curses.COLOR_WHITE, 0),
             "negra": (curses.COLOR_WHITE, curses.COLOR_BLACK, 0),
             "mensaje": (curses.COLOR_WHITE, curses.COLOR_BLUE, curses.A_BOLD),
             "barra": (curses.COLOR_YELLOW, curses.COLOR_BLUE, curses.A_BOLD),
             "barra_vacia": (curses.COLOR_CYAN, curses.COLOR_BLUE, 0),
             "hecha": (curses.COLOR_GREEN, curses.COLOR_BLUE, curses.A_BOLD),
             "actual": (curses.COLOR_YELLOW, curses.COLOR_BLUE, curses.A_BOLD),
             "pendiente": (curses.COLOR_WHITE, curses.COLOR_BLUE, 0),
             "credito": (curses.COLOR_CYAN, curses.COLOR_BLUE, 0)}
    attrs = {}
    for n, (estilo, (frente, fondo, extra)) in enumerate(pares.items(), start=1):
        curses.init_pair(n, frente, fondo)
        attrs[estilo] = curses.color_pair(n) | extra
    scr.bkgd(" ", attrs["fondo"])
    scr.nodelay(True)
    curses.flushinp()                       # lo tecleado antes de empezar no llega a la consola después
    nombre_sonido, estimado = nombres_y_estimados()
    inicio = time.monotonic()
    while True:
        while scr.getch() != -1:            # lo que se teclee mientras carga se descarta
            pass
        try:
            with open(args.progreso, encoding="utf-8") as f:
                eventos = leer_progreso(f.read())
        except OSError:
            eventos = []
        if args.listo and os.path.exists(args.listo) and not any(e[1] == "listo" for e in eventos):
            eventos.append((time.time(), "listo", []))
        r = resumen(eventos, time.time(), nombre_salida_pipewire, nombre_sonido, estimado)
        alto, ancho = scr.getmaxyx()
        scr.erase()
        for y, x, texto, estilo in componer(ancho, alto, r):
            try:      # en la esquina inferior derecha curses dibuja y DESPUÉS da error (no puede avanzar): se ignora
                scr.addstr(y, x, texto[:max(0, ancho - x)], attrs.get(estilo, 0))
            except curses.error:
                pass
        scr.refresh()
        if r["listo"]:
            time.sleep(0.6)                 # el 100 % se ve un instante
            break
        if time.monotonic() - inicio > args.maximo:
            break
        time.sleep(0.2)
    curses.flushinp()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pantalla de inicio del piano mientras carga (estilo DOS).")
    ap.add_argument("--progreso", default=os.path.join(RUNDIR, "piano-vivo.progreso"))
    ap.add_argument("--listo", default=os.path.join(RUNDIR, "piano-vivo.listo"))
    ap.add_argument("--maximo", type=float, default=150.0, help="segundos como mucho (después termina sola)")
    args = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # piano-teclado.sh la cierra si el piano falla
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(correr, args)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
