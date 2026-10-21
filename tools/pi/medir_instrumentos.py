#!/usr/bin/env python3
"""Mide en la Raspberry los instrumentos del catálogo para igualar su nivel y comprobar que son tocables.

Para cada instrumento (con sus controles iniciales aplicados al principio de cada pieza):
  - render offline con sfizz_render (float 32) de 02-acordes-pedal: RMS y pico -> ganancia que iguala su RMS
    con el del instrumento de referencia (Salamander, ganancia 0 dB)
  - render de 04-prueba-pedal: cola sin pedal frente a cola con pedal -> ¿sostiene con el CC64?
  - render de 05-afinacion (La4): frecuencia fundamental -> desviación en cents de 440 Hz (detecta errores de
    octava en el mapeo de un SFZ, p. ej. una muestra en la tecla equivocada)
  - con --tiempo-real: lo toca en tiempo real EN SILENCIO (escuchar-midi.sh -s, quantum 512, núcleos 2-3) con
    03-arpegios-densos y anota carga (B/Q), cortes (xruns), RAM máxima de sfizz y tiempo de carga. La salida se
    GRABA: una medición sin audio (pico < AUDIO_MIN_DBFS) es un error, no una carga baja. Se repite una vez
    (fallo intermitente del camino de prueba "Midi Through", no del piano en vivo) y queda anotado.
    Con --rendimiento, gobernador "performance" durante la medición (como `piano -p`), restaurado al final.

Uso: medir_instrumentos.py [--tiempo-real [--rendimiento]] [--json RESULTADOS] [--catalogo-salida JSON] [id ...]
No suena nada por la G1. Se niega a medir si el piano está en uso.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import analizar_wav  # noqa: E402
import catalogo_instrumentos as cat  # noqa: E402
import generar_midis_prueba as gen  # noqa: E402

SFIZZ_RENDER = os.path.expanduser("~/piano/bin/sfizz_render")
SFIZZ_JACK = os.path.expanduser("~/piano/bin/sfizz_jack")
PIEZA_NIVEL = "02-acordes-pedal.mid"
PIEZA_PEDAL = "04-prueba-pedal.mid"
PIEZA_CARGA = "03-arpegios-densos.mid"
PIEZA_AFINACION = "05-afinacion.mid"
AFINACION_MAX_CENTS = 50.0   # más desviación que esto es un instrumento mal mapeado o desafinado
REFERENCIA = "salamander"
PEDAL_MIN_DB = 10.0          # la cola con pedal debe superar en esto a la cola sin pedal
COLA_AUDIBLE_DBFS = -60.0    # si sin pedal la cola ya suena así, el instrumento no se corta al soltar (arpa...)
PICO_MAX_DBFS = -9.0         # la ganancia no deja el pico por encima de esto (Salamander: -9,8 dBFS)
AUDIO_MIN_DBFS = -60.0       # por debajo, la medición en tiempo real no tuvo sonido (no vale)
GOBERNADOR = "/sys/devices/system/cpu/cpufreq/policy0/scaling_governor"
CLIENTE_PRUEBA = "piano-prueba"


def combinar_rms(rms_canales):
    """RMS conjunto (potencia media) de varios canales en dBFS; -inf si todos son silencio."""
    potencias = [10 ** (r / 10) for r in rms_canales if r != -math.inf]
    if not potencias:
        return -math.inf
    return 10 * math.log10(sum(potencias) / len(rms_canales))


def ganancia_para(rms_referencia, rms, pico=None, pico_max=PICO_MAX_DBFS):
    """Ganancia (dB, 0,1 dB) que lleva rms al nivel de la referencia, sin dejar el pico por encima de pico_max
    (instrumentos de ataque muy marcado, como el arpa) y dentro de los límites del catálogo."""
    if rms == -math.inf or rms_referencia == -math.inf:
        raise ValueError("no se puede igualar un render en silencio")
    g = rms_referencia - rms
    if pico is not None and pico != -math.inf:
        g = min(g, pico_max - pico)
    return max(cat.GANANCIA_MIN, min(cat.GANANCIA_MAX, round(g, 1))) + 0.0


def evaluar_pedal(rms_sin, rms_con):
    """("sí" | "no aplica" | "NO", diferencia en dB).
    sí: la cola con pedal supera a la de sin pedal en PEDAL_MIN_DB. no aplica: sin pedal la cola ya suena (el
    instrumento no se corta al soltar la tecla: arpa, marimba...). NO: se corta al soltar y el pedal no lo sostiene."""
    if rms_con == -math.inf:
        return "NO", -math.inf
    dif = math.inf if rms_sin == -math.inf else rms_con - rms_sin
    if dif >= PEDAL_MIN_DB:
        return "sí", dif
    return ("no aplica" if rms_sin > COLA_AUDIBLE_DBFS else "NO"), dif


def cents(f, referencia=gen.FRECUENCIA_AFINACION):
    return None if not f else 1200 * math.log2(f / referencia)


def resumen_escuchar(texto, nodo=CLIENTE_PRUEBA):
    """Extrae de la salida de escuchar-midi.sh: carga, cortes y tiempo de carga del nodo, y el pico grabado."""
    r = {"bq_max": None, "bq_medio": None, "xruns": None, "carga_s": None, "pico": None}
    m = re.search(rf"^\s*{re.escape(nodo)}\s+B/Q máx ([0-9.]+), medio ([0-9.]+), xruns (-?\d+)\s*$", texto, re.M)
    if m:
        r.update(bq_max=float(m.group(1)), bq_medio=float(m.group(2)), xruns=int(m.group(3)))
    m = re.search(r"listo en (\d+) s", texto)
    if m:
        r["carga_s"] = int(m.group(1))
    picos = [-math.inf if v == "-inf" else float(v)
             for v in re.findall(r"nivel: canal \d+: pico ([-+]?[0-9.]+|-inf) dBFS", texto)]
    if picos:
        r["pico"] = max(picos)
    return r


def preparar_midi(origen, destino, controles, transposicion=0):
    """La pieza con los controles iniciales del instrumento y su transposición (lo que hará el enrutador)."""
    with open(origen, "rb") as f:
        datos = f.read()
    with open(destino, "wb") as f:
        f.write(gen.transponer_smf(gen.anteponer_controles(datos, list(controles)), transposicion))


def render(sfizz_render, inst, midi, wav):
    t0 = time.monotonic()
    p = subprocess.run([sfizz_render, "--sfz", inst.sfz, "--midi", midi, "--wav", wav, "-s", "44100",
                        "-b", "512", "-q", "1", "-p", str(inst.voces), "--use-eot"],
                       capture_output=True, text=True)
    if p.returncode != 0 or not os.path.isfile(wav):
        raise RuntimeError(f"sfizz_render falló ({p.returncode}): {(p.stdout + p.stderr)[-300:]}")
    return time.monotonic() - t0


def medir_offline(inst, midis, tmp, sfizz_render):
    r = {}
    nivel_mid = os.path.join(tmp, f"{inst.id}-nivel.mid")
    pedal_mid = os.path.join(tmp, f"{inst.id}-pedal.mid")
    preparar_midi(os.path.join(midis, PIEZA_NIVEL), nivel_mid, inst.controles, inst.transposicion)
    preparar_midi(os.path.join(midis, PIEZA_PEDAL), pedal_mid, inst.controles, inst.transposicion)
    afin_mid = os.path.join(tmp, f"{inst.id}-afinacion.mid")
    preparar_midi(os.path.join(midis, PIEZA_AFINACION), afin_mid, inst.controles, inst.transposicion)
    wav = os.path.join(tmp, f"{inst.id}-nivel.wav")
    r["render_s"] = round(render(sfizz_render, inst, nivel_mid, wav), 1)
    canales = analizar_wav.niveles(wav)
    r["pico"] = max(c[0] for c in canales)
    r["rms"] = combinar_rms([c[1] for c in canales])
    r["sobre_0dbfs"] = sum(c[2] for c in canales)
    wav = os.path.join(tmp, f"{inst.id}-pedal.wav")
    render(sfizz_render, inst, pedal_mid, wav)
    sin = combinar_rms([c[1] for c in analizar_wav.niveles(wav, *gen.VENTANA_SIN_PEDAL)])
    con = combinar_rms([c[1] for c in analizar_wav.niveles(wav, *gen.VENTANA_CON_PEDAL)])
    r["pedal"], r["pedal_db"] = evaluar_pedal(sin, con)
    r["pedal_ok"] = r["pedal"] != "NO"
    r["cola_sin_pedal"], r["cola_con_pedal"] = sin, con
    wav = os.path.join(tmp, f"{inst.id}-afinacion.wav")
    render(sfizz_render, inst, afin_mid, wav)
    frecuencia, _, canales = analizar_wav.leer_wav(wav)
    r["afinacion_cents"] = cents(analizar_wav.frecuencia_fundamental(canales, frecuencia, *gen.VENTANA_AFINACION))
    r["afinacion_ok"] = r["afinacion_cents"] is not None and abs(r["afinacion_cents"]) <= AFINACION_MAX_CENTS
    return r


class MedidorRam(threading.Thread):
    """RAM residente máxima (MB) del proceso sfizz_jack de prueba mientras dura la medición."""

    def __init__(self, patron):
        super().__init__(daemon=True)
        self.patron, self.max_mb, self.parar = patron, 0.0, threading.Event()

    def run(self):
        while not self.parar.wait(0.5):
            p = subprocess.run(["pgrep", "-f", self.patron], capture_output=True, text=True)
            for pid in p.stdout.split():
                try:
                    with open(f"/proc/{pid}/status") as f:
                        for linea in f:
                            if linea.startswith("VmRSS:"):
                                self.max_mb = max(self.max_mb, int(linea.split()[1]) / 1024)
                except OSError:
                    pass


def medir_tiempo_real(inst, midis, tmp, intentos=2):
    """Mide en tiempo real; si una pasada sale sin audio la repite (hasta `intentos`). Anota los intentos y la
    salida de las pasadas sin audio para poder diagnosticarlas."""
    carga_mid = os.path.join(tmp, f"{inst.id}-carga.mid")
    preparar_midi(os.path.join(midis, PIEZA_CARGA), carga_mid, inst.controles, inst.transposicion)
    sin_audio = []
    for intento in range(1, intentos + 1):
        r, salida = _pasada_tiempo_real(inst, carga_mid, os.path.join(tmp, f"{inst.id}-tiempo-real-{intento}"))
        if "sin audio" not in r.get("error", ""):
            break
        sin_audio.append(salida[-1500:])
    r["intentos"] = intento
    if sin_audio:
        r["salidas_sin_audio"] = sin_audio
    return r


def _pasada_tiempo_real(inst, carga_mid, grabaciones):
    comando = (f"taskset -c 2,3 {SFIZZ_JACK} --client_name {{CLIENTE}} --num_voices {inst.voces} "
               f"--preload_size 8192 --sample_quality 1 '{inst.sfz}'")
    entorno = dict(os.environ, PIANO_CMD=comando, PIANO_LISTO="Instrument loaded")
    ram = MedidorRam(f"^\\S*sfizz_jack --client_name {CLIENTE_PRUEBA} ")
    ram.start()
    try:
        p = subprocess.run(["bash", os.path.join(DIR, "escuchar-midi.sh"), "-s", "-q", "512", "-r", grabaciones,
                            carga_mid], capture_output=True, text=True, env=entorno)
    finally:
        ram.parar.set()
        ram.join()
    r = resumen_escuchar(p.stdout + p.stderr)
    r["ram_mb"] = round(ram.max_mb)
    if p.returncode != 0 or r["xruns"] is None:
        r["error"] = (p.stdout + p.stderr)[-400:]
    elif r["pico"] is None or r["pico"] < AUDIO_MIN_DBFS:
        r["error"] = f"sin audio en la grabación (pico {r['pico']} dBFS): la medición no vale"
    return r, p.stdout + p.stderr


def piano_en_uso():
    # Patrón anclado: una shell cuyo texto de orden mencione la interfaz no cuenta como piano en uso.
    ui = subprocess.run(["pgrep", "-f", r"^python3 \S*teclado_piano\.py --titulo"], capture_output=True).returncode == 0
    motor = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "piano-vivo-cadena"]).returncode == 0
    return ui or motor


def fmt(x, ancho=6, dec=1):
    if x is None:
        return "—".rjust(ancho)
    if x in (math.inf, -math.inf):
        return ("+inf" if x > 0 else "-inf").rjust(ancho)
    return f"{x:{ancho}.{dec}f}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="*", help="instrumentos a medir (por defecto, todos los disponibles)")
    ap.add_argument("--catalogo", default=cat.RUTA_CATALOGO)
    ap.add_argument("--base", default=cat.BASE_INSTRUMENTOS)
    ap.add_argument("--midis", default=None, help="carpeta con las piezas (por defecto se generan)")
    ap.add_argument("--sfizz-render", default=SFIZZ_RENDER)
    ap.add_argument("--tiempo-real", action="store_true")
    ap.add_argument("--rendimiento", action="store_true", help="gobernador performance durante la medición")
    ap.add_argument("--json", help="guarda aquí los resultados")
    ap.add_argument("--catalogo-salida", help="escribe una copia del catálogo con las ganancias medidas")
    args = ap.parse_args(argv)

    if args.tiempo_real and piano_en_uso():
        print("El piano está en uso: no se mide en tiempo real (detendría el piano).", file=sys.stderr)
        return 4
    todos = cat.cargar(args.catalogo, args.base)
    hay = cat.disponibles(todos)
    pedidos = args.ids or [i.id for i in hay]
    desconocidos = [i for i in pedidos if cat.buscar(hay, i) is None]
    if desconocidos:
        print(f"ERROR: no disponibles en el catálogo: {', '.join(desconocidos)}", file=sys.stderr)
        return 2
    ref = cat.buscar(hay, REFERENCIA)
    if ref is None:
        print(f"ERROR: falta el instrumento de referencia ({REFERENCIA})", file=sys.stderr)
        return 2
    orden = [REFERENCIA] + [i for i in pedidos if i != REFERENCIA]

    gob_original = None
    resultados = {}
    with tempfile.TemporaryDirectory() as tmp:
        midis = args.midis
        if midis is None:
            midis = os.path.join(tmp, "midis")
            os.makedirs(midis)
            for nombre in (PIEZA_NIVEL, PIEZA_PEDAL, PIEZA_CARGA, PIEZA_AFINACION):
                gen.escribir_smf(os.path.join(midis, nombre), gen.PIEZAS[nombre]())
        try:
            if args.tiempo_real and args.rendimiento:
                with open(GOBERNADOR) as f:
                    gob_original = f.read().strip()
                subprocess.run(["sudo", "-n", "tee", GOBERNADOR], input="performance", text=True,
                               capture_output=True, check=True)
            for iid in orden:
                inst = cat.buscar(hay, iid)
                print(f"== {inst.nombre}", flush=True)
                try:
                    r = medir_offline(inst, midis, tmp, args.sfizz_render)
                except (RuntimeError, ValueError) as e:
                    r = {"error": str(e)}
                if args.tiempo_real and iid in pedidos and "error" not in r:
                    r["tiempo_real"] = medir_tiempo_real(inst, midis, tmp)
                resultados[iid] = r
        finally:
            if gob_original:
                subprocess.run(["sudo", "-n", "tee", GOBERNADOR], input=gob_original, text=True,
                               capture_output=True)

    rms_ref = resultados[REFERENCIA].get("rms", -math.inf)
    print()
    print(f"{'id':11} {'RMS':>6} {'pico':>6} {'gan.':>6} {'pico+g':>6} {'pedal':>9} {'afin.':>6} {'render':>6}"
          + ("  B/Q máx  medio  xruns   RAM  carga   pico  int." if args.tiempo_real else ""))
    for iid in orden:
        r = resultados[iid]
        if "error" in r:
            print(f"{iid:11} ERROR: {r['error'][:100]}")
            continue
        r["ganancia_db"] = ganancia_para(rms_ref, r["rms"], r["pico"])
        r["limitada_por_pico"] = r["ganancia_db"] < round(rms_ref - r["rms"], 1)
        r["pico_con_ganancia"] = r["pico"] + r["ganancia_db"]
        pedal = "n/a" if r["pedal"] == "no aplica" else (r["pedal"] + " " + fmt(r["pedal_db"], 5, 0))
        afin = "—" if r.get("afinacion_cents") is None else f"{r['afinacion_cents']:+.0f}c"
        if not r.get("afinacion_ok", True):
            afin += "!"
        linea = (f"{iid:11} {fmt(r['rms'])} {fmt(r['pico'])} {r['ganancia_db']:+5.1f}{'p' if r['limitada_por_pico'] else ' '}"
                 f"{fmt(r['pico_con_ganancia'])}"
                 f" {pedal:>9} {afin:>6} {fmt(r['render_s'], 5)}s")
        t = r.get("tiempo_real")
        if t:
            linea += (f"  {fmt(t['bq_max'], 7, 2)} {fmt(t['bq_medio'], 6, 2)} {t['xruns'] if t['xruns'] is not None else '—':>6}"
                      f" {t['ram_mb']:>4}MB {t['carga_s'] if t['carga_s'] is not None else '—':>4}s {fmt(t['pico'])}"
                      f" {t.get('intentos', 1):>4}")
            if t.get("error"):
                linea += "  (ERROR, ver JSON)"
        print(linea)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultados, f, indent=2, ensure_ascii=False, default=str)
    if args.catalogo_salida:
        with open(args.catalogo, encoding="utf-8") as f:
            datos = json.load(f)
        for d in datos["instrumentos"]:
            r = resultados.get(d["id"], {})
            if "ganancia_db" in r and d["id"] != REFERENCIA:
                d["ganancia_db"] = r["ganancia_db"]
        with open(args.catalogo_salida, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
            f.write("\n")
    fallidos = [i for i in orden if "error" in resultados[i]
                or "error" in resultados[i].get("tiempo_real", {}) or not resultados[i].get("pedal_ok")
                or not resultados[i].get("afinacion_ok", True)]
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
