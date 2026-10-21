#!/usr/bin/env python3
"""Mide niveles de un WAV (PCM 16/24/32 o float 32, también WAVE_FORMAT_EXTENSIBLE).

Uso: analizar_wav.py ARCHIVO.wav [--max-dbfs X] [--desde S] [--hasta S]
Imprime duración, pico y RMS por canal (dBFS) y cuántas muestras alcanzan o superan 0 dBFS.
Con --max-dbfs, termina con código 1 si el pico de algún canal supera X dBFS.
Con --desde/--hasta (segundos), mide solo ese tramo (p. ej. la cola de una nota).
Sin dependencias externas.
"""
import argparse
import math
import struct
import sys
from array import array

PCM, IEEE_FLOAT, EXTENSIBLE = 1, 3, 0xFFFE


def leer_wav(ruta):
    """Devuelve (frecuencia, canales, lista de muestras por canal normalizadas a ±1.0)."""
    with open(ruta, "rb") as f:
        datos = f.read()
    if len(datos) < 12 or datos[:4] != b"RIFF" or datos[8:12] != b"WAVE":
        raise ValueError("no es un archivo RIFF/WAVE")
    i, fmt, crudo = 12, None, None
    while i + 8 <= len(datos):
        cid, tam = datos[i:i + 4], struct.unpack("<I", datos[i + 4:i + 8])[0]
        cuerpo = i + 8
        if cid == b"fmt ":
            fmt = datos[cuerpo:cuerpo + tam]
        elif cid == b"data":
            # Un WAV sin cerrar (grabación interrumpida) puede declarar 0 o 0xFFFFFFFF: usar lo que haya.
            fin = len(datos) if tam in (0, 0xFFFFFFFF) or cuerpo + tam > len(datos) else cuerpo + tam
            crudo = datos[cuerpo:fin]
            break
        i = cuerpo + tam + (tam & 1)
    if fmt is None or crudo is None:
        raise ValueError("faltan los bloques 'fmt ' o 'data'")
    formato, canales, frecuencia = struct.unpack("<HHI", fmt[:8])
    bits = struct.unpack("<H", fmt[14:16])[0]
    if formato == EXTENSIBLE:
        if len(fmt) < 26:
            raise ValueError("cabecera EXTENSIBLE incompleta")
        formato = struct.unpack("<H", fmt[24:26])[0]   # primeros 2 bytes del SubFormat GUID
    if canales < 1:
        raise ValueError("número de canales inválido")

    ancho = bits // 8
    util = len(crudo) - len(crudo) % (ancho * canales)
    crudo = crudo[:util]
    if formato == IEEE_FLOAT and bits == 32:
        valores = array("f")
        valores.frombytes(crudo)
    elif formato == PCM and bits in (16, 32):
        enteros = array("h" if bits == 16 else "i")
        enteros.frombytes(crudo)
        if sys.byteorder != "little":
            enteros.byteswap()
        escala = 1.0 / (32768.0 if bits == 16 else 2147483648.0)
        valores = array("f", (v * escala for v in enteros))
    elif formato == PCM and bits == 24:
        valores = array("f", (int.from_bytes(crudo[k:k + 3], "little", signed=True) / 8388608.0
                              for k in range(0, len(crudo), 3)))
    else:
        raise ValueError(f"formato no soportado: {formato} con {bits} bits")
    if formato == IEEE_FLOAT and sys.byteorder != "little":
        valores.byteswap()
    # Arrays compactos (4 bytes por muestra): un WAV estéreo de 5 min ocupa ~50 MB, no cientos.
    return frecuencia, canales, [valores[c::canales] for c in range(canales)]


def dbfs(x):
    return -math.inf if x <= 0 else 20 * math.log10(x)


def medir(canal):
    if not canal:
        return {"pico": 0.0, "rms": 0.0, "sobre_0dbfs": 0}
    pico = max(abs(v) for v in canal)
    rms = math.sqrt(sum(v * v for v in canal) / len(canal))
    return {"pico": pico, "rms": rms, "sobre_0dbfs": sum(1 for v in canal if abs(v) >= 1.0)}


def tramo(frecuencia, muestras, desde=None, hasta=None):
    """Recorta los canales a [desde, hasta) segundos. Error si el tramo queda vacío o fuera del archivo."""
    n = len(muestras[0]) if muestras else 0
    i = 0 if desde is None else int(round(desde * frecuencia))
    j = n if hasta is None else int(round(hasta * frecuencia))
    if i < 0 or j > n or i >= j:
        raise ValueError(f"tramo {desde}..{hasta} s fuera del archivo ({n / frecuencia:.2f} s)")
    return [c[i:j] for c in muestras]


def niveles(ruta, desde=None, hasta=None):
    """[(pico_dbfs, rms_dbfs, muestras >= 0 dBFS) por canal] del archivo o de un tramo."""
    frecuencia, _, muestras = leer_wav(ruta)
    resultado = []
    for canal in tramo(frecuencia, muestras, desde, hasta):
        m = medir(canal)
        resultado.append((dbfs(m["pico"]), dbfs(m["rms"]), m["sobre_0dbfs"]))
    return resultado


def frecuencia_fundamental(canales, frecuencia, desde, hasta=None, fmin=50.0, fmax=2000.0, umbral=0.15):
    """Frecuencia fundamental (Hz) de un tramo, por el método YIN (de Cheveigné y Kawahara, 2002): diferencia
    cuadrática por desfase, normalizada por su media acumulada; el primer mínimo bajo el umbral es el periodo
    (evita confundir la octava con armónicos fuertes). Mezcla los canales y diezma a ~22 kHz (Python puro).
    None si no hay periodicidad clara."""
    paso = max(1, int(frecuencia // 22050))
    sr = frecuencia / paso
    i0 = int(desde * frecuencia)
    i1 = len(canales[0]) if hasta is None else min(len(canales[0]), int(hasta * frecuencia))
    mono = [sum(c[k] for c in canales) / len(canales) for k in range(i0, i1, paso)]
    tau_min, tau_max = max(2, int(sr / fmax)), int(sr / fmin)
    ventana = min(1024, len(mono) - tau_max - 2)
    if ventana < 2 * tau_min or tau_max >= len(mono):
        return None
    x = mono
    d = [0.0] * (tau_max + 2)
    for tau in range(1, tau_max + 2):
        d[tau] = sum((a - b) * (a - b) for a, b in zip(x[:ventana], x[tau:tau + ventana]))
    acumulado, dn = 0.0, [1.0] * (tau_max + 2)
    for tau in range(1, tau_max + 2):
        acumulado += d[tau]
        dn[tau] = d[tau] * tau / acumulado if acumulado > 0 else 1.0
    tau = next((t for t in range(tau_min, tau_max + 1) if dn[t] < umbral), None)
    if tau is None:
        tau = min(range(tau_min, tau_max + 1), key=lambda t: dn[t])
        if dn[tau] > 0.5:
            return None
    while tau + 1 <= tau_max and dn[tau + 1] < dn[tau]:
        tau += 1
    a, b, c = dn[tau - 1], dn[tau], dn[tau + 1]          # interpolación parabólica del mínimo
    den = a - 2 * b + c
    fino = tau + (0.5 * (a - c) / den if den else 0.0)
    return sr / fino


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("wav")
    ap.add_argument("--max-dbfs", type=float, default=None)
    ap.add_argument("--desde", type=float, default=None, help="inicio del tramo a medir (s)")
    ap.add_argument("--hasta", type=float, default=None, help="fin del tramo a medir (s)")
    args = ap.parse_args(argv)
    frecuencia, canales, muestras = leer_wav(args.wav)
    n = len(muestras[0])
    print(f"duración {n / frecuencia:.1f} s, {frecuencia} Hz, {canales} canal(es)")
    if args.desde is not None or args.hasta is not None:
        try:
            muestras = tramo(frecuencia, muestras, args.desde, args.hasta)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        print(f"tramo {args.desde or 0:.2f}..{(args.hasta if args.hasta is not None else n / frecuencia):.2f} s")
    excede = False
    for c, canal in enumerate(muestras):
        m = medir(canal)
        print(f"canal {c + 1}: pico {dbfs(m['pico']):+.1f} dBFS, RMS {dbfs(m['rms']):+.1f} dBFS, "
              f"muestras >= 0 dBFS: {m['sobre_0dbfs']}")
        if args.max_dbfs is not None and dbfs(m["pico"]) > args.max_dbfs:
            excede = True
    if excede:
        print(f"EXCEDE el límite de {args.max_dbfs:+.1f} dBFS")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
