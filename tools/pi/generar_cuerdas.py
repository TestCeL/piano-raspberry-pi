#!/usr/bin/env python3
"""Genera un ensemble de cuerdas que cubre todo el teclado a partir de las secciones de VSCO 2 CE (fase 08).

Cada sección suena solo en su franja (sin solaparse, para no duplicar voces en la Pi 3):
  contrabajo hasta Si1 | chelos Do2–Si2 | violas Do3–Fa#3 | violines desde Sol3
Se conservan las regiones (capas de dinámica, nota de referencia) y las envolventes de cada sección; la región
más grave del contrabajo se extiende hasta La0. No modifica los SFZ originales: escribe uno nuevo junto a ellos.

Uso: generar_cuerdas.py CARPETA_VSCO2 [SALIDA.sfz]
"""
import os
import re
import sys

# (sfz de la sección, tecla más grave, tecla más aguda) — MIDI: 36 = Do2, 48 = Do3, 55 = Sol3
SECCIONES = (("ContrabassSusVB.sfz", 21, 35), ("CelloEnsSusVib.sfz", 36, 47), ("ViolaEnsSusVib.sfz", 48, 54),
             ("ViolinEnsSusVib.sfz", 55, 108))
NOMBRE_SALIDA = "Cuerdas ensemble (piano digital).sfz"
NOTAS = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
TOKEN = re.compile(r"<(\w+)>|(\w+)=")


def nota_midi(valor):
    """Número MIDI de un valor SFZ: número, o nombre de nota (c4 = 60, c#4, db4)."""
    v = valor.strip().lower()
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    m = re.fullmatch(r"([a-g])([#b]?)(-?\d+)", v)
    if not m:
        raise ValueError(f"nota no reconocida: {valor}")
    alt = {"#": 1, "b": -1, "": 0}[m.group(2)]
    return 12 * (int(m.group(3)) + 1) + NOTAS[m.group(1)] + alt


def analizar(texto):
    """Lista de (cabecera, {opcode: valor}) de un SFZ. Quita comentarios // y admite valores con espacios
    (p. ej. rutas de muestras): un valor llega hasta el siguiente opcode o cabecera."""
    texto = re.sub(r"//[^\n]*", "", texto.replace("\r", ""))
    bloques, actual = [], None
    marcas = list(TOKEN.finditer(texto))
    for k, m in enumerate(marcas):
        fin = marcas[k + 1].start() if k + 1 < len(marcas) else len(texto)
        if m.group(1):
            actual = (m.group(1), {})
            bloques.append(actual)
        elif actual is not None:
            actual[1][m.group(2)] = texto[m.end():fin].strip()
    return bloques


def regiones(bloques):
    """[(default_path, opcodes efectivos de la región)] combinando <control>, <global>, <master>, <group>."""
    resultado, ruta, niveles = [], "", {"global": {}, "master": {}, "group": {}}
    for cabecera, opc in bloques:
        if cabecera == "control":
            ruta = opc.get("default_path", ruta)
        elif cabecera == "global":
            niveles = {"global": dict(opc), "master": {}, "group": {}}
        elif cabecera == "master":
            niveles["master"], niveles["group"] = dict(opc), {}
        elif cabecera == "group":
            niveles["group"] = dict(opc)
        elif cabecera == "region":
            efectivo = {**niveles["global"], **niveles["master"], **niveles["group"], **opc}
            resultado.append((ruta.replace("\\", "/"), efectivo))
    return resultado


def recortar(regs, lo, hi):
    """Regiones limitadas a la franja [lo, hi] (las que quedan fuera se descartan)."""
    salida = []
    for ruta, opc in regs:
        o = dict(opc)
        if "key" in o:
            k = nota_midi(o.pop("key"))
            o.setdefault("lokey", str(k))
            o.setdefault("hikey", str(k))
            o.setdefault("pitch_keycenter", str(k))
        a = max(lo, nota_midi(o.get("lokey", "0")))
        b = min(hi, nota_midi(o.get("hikey", "127")))
        if a > b:
            continue
        o["lokey"], o["hikey"] = str(a), str(b)
        salida.append((ruta, o))
    return salida


def generar(carpeta, secciones=None, extender_grave=True):
    """Texto del SFZ del ensemble. Los opcodes se escriben en orden estable (sample primero)."""
    secciones = secciones or SECCIONES
    partes = ["// Ensemble de cuerdas para el piano digital (generado por generar_cuerdas.py; no editar a mano).",
              "// Fuente: VSCO 2 Community Edition (Versilian Studios, CC0). Secciones sin solaparse:"]
    todas = []
    for sfz, lo, hi in secciones:
        with open(os.path.join(carpeta, sfz), encoding="utf-8", errors="replace") as f:
            regs = recortar(regiones(analizar(f.read())), lo, hi)
        if not regs:
            raise ValueError(f"{sfz}: ninguna región en la franja {lo}-{hi}")
        todas.append((sfz, regs))
    if extender_grave:          # la región más grave del contrabajo baja hasta La0 (21)
        sfz, regs = todas[0]
        idx = min(range(len(regs)), key=lambda i: int(regs[i][1]["lokey"]))
        bajas = [i for i, (_, o) in enumerate(regs) if o["lokey"] == regs[idx][1]["lokey"]]
        for i in bajas:
            regs[i][1]["lokey"] = str(min(int(regs[i][1]["lokey"]), secciones[0][1]))
    for sfz, regs in todas:              # resumen con las franjas finales (tras la extensión del grave)
        partes.append(f"//   {sfz}: teclas {min(int(o['lokey']) for _, o in regs)}-{max(int(o['hikey']) for _, o in regs)}")
    for sfz, regs in todas:
        partes.append(f"\n// --- {sfz}")
        for ruta, o in regs:
            partes.append(f"<control> default_path={ruta}" if ruta else "<control>")
            orden = ["sample"] + sorted(k for k in o if k != "sample")
            partes.append("<region> " + " ".join(f"{k}={o[k]}" for k in orden if k in o))
    return "\n".join(partes) + "\n"


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    carpeta = argv[1]
    salida = argv[2] if len(argv) == 3 else os.path.join(carpeta, NOMBRE_SALIDA)
    texto = generar(carpeta)
    with open(salida, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    print(f"{salida}: {texto.count('<region>')} regiones")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
