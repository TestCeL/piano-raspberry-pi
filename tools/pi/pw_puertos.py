#!/usr/bin/env python3
"""Lista los puertos PipeWire de un nodo, con su dirección y tipo, a partir de `pw-dump`.

Uso: pw-dump | pw_puertos.py NOMBRE_NODO
Salida (una línea por puerto, ordenada por nombre):  <in|out> <midi|audio|otro> <nodo:puerto>
"""
import json
import sys


def tipo_de(props):
    dsp = props.get("format.dsp", "")
    if "midi" in dsp or "UMP" in dsp:
        return "midi"
    if "audio" in dsp:
        return "audio"
    return "otro"


def puertos_de_nodo(objetos, nombre_nodo):
    nodos = {
        o["id"]: o["info"]["props"].get("node.name", "")
        for o in objetos
        if o.get("type") == "PipeWire:Interface:Node" and o.get("info")
    }
    ids = {i for i, n in nodos.items() if n == nombre_nodo}
    resultado = []
    for o in objetos:
        if o.get("type") != "PipeWire:Interface:Port" or not o.get("info"):
            continue
        props = o["info"]["props"]
        if props.get("node.id") not in ids:
            continue
        direccion = "in" if o["info"].get("direction") == "input" else "out"
        resultado.append((direccion, tipo_de(props), f"{nombre_nodo}:{props.get('port.name', '')}"))
    return sorted(resultado, key=lambda r: r[2])


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    objetos = json.load(sys.stdin)
    for fila in puertos_de_nodo(objetos, argv[1]):
        print(" ".join(fila))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
